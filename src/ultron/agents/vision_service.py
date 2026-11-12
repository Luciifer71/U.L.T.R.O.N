"""Vision service: the only process that opens the camera.

Modes
-----
* **off** (default): the camera is closed.
* **presence** (``ULTRON_PRESENCE=1``): face check 10×/s at 320×240 so the entity
  can notice you sit down (``ultron.signal.gaze``).
* **gesture**: hand tracking ~30×/s at 640×480 with MediaPipe (two hands, 21
  landmarks each), stabilised by :mod:`ultron.gestures.tracker`. Publishes the
  tracked hands (``ultron.signal.hands``) and pose events
  (``ultron.signal.gesture``) for the holographic hands in the UI.

Gesture mode is switched on/off through ``ultron.vision.control`` by voice (brain),
a double clap (listener) or the Ops panel, and off again by both palms held for 1 s,
voice, the panel, or 3 minutes without hands. The current state is published on
``ultron.vision.state``.

Privacy: frames live only for one detection and are never stored, logged or sent.
Only landmark coordinates and pose names leave this process. Display only: nothing
here triggers desktop actions (those arrive in later gesture stages and go
through the capability broker).
"""
import asyncio
import json
import logging
import os
import time

from ultron.agents.presence_watcher import FRAME_HEIGHT, FRAME_WIDTH, PresenceTracker, face_detector, largest_face
from ultron.control.operations import heartbeat_loop
from ultron.control.signals import SignalPublisher
from ultron.gestures.activation import CONTROL_SUBJECT, STATE_SUBJECT
from ultron.gestures.tracker import GestureTracker

# Most laptop webcams have a 16:9 sensor. Asking for 4:3 (640x480) makes the
# driver crop off the left and right of the view, so hands vanished well before
# the edge of what the camera sees. MediaPipe scales frames down internally, so
# the larger picture costs little. Override with ULTRON_GESTURE_RESOLUTION=WxH.
GESTURE_WIDTH = 1280
GESTURE_HEIGHT = 720
GESTURE_RATE_HZ = 30.0
PRESENCE_RATE_HZ = 10.0
HAND_MODEL = 'hand_landmarker.task'
COMMANDS = frozenset({'gesture_on', 'gesture_off', 'gesture_toggle', 'status'})
SPOKEN_SOURCES = frozenset({'clap', 'gesture', 'idle'})  # voice and panel requests answer for themselves

logger = logging.getLogger('ultron.vision')


class MediaPipeHands:
    """Thin wrapper around MediaPipe's hand landmarker in video mode."""

    def __init__(self, model_path=None):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        from ultron.paths import project_root
        path = model_path or project_root() / 'assets' / 'models' / HAND_MODEL
        if not os.path.isfile(path):
            raise RuntimeError(f'Hand model missing: {path}')
        self._mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ms = 0

    def detect(self, frame_bgr, now):
        """Hands in a camera frame, as the user sees them in a mirror.

        Returns [(side, 21 image landmarks, score, 21 world landmarks)].

        The frame is passed un-mirrored on purpose: this hand model labels hands
        correctly on a normal camera picture (verified on MediaPipe's own
        left_hands/right_hands test images; its docs say otherwise) and mirroring
        first swaps left and right. Coordinates are mirrored afterwards (x -> 1-x)
        so the picture still behaves like a mirror.
        """
        import cv2
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        timestamp = max(self._last_ms + 1, int(now * 1000))  # must strictly increase
        self._last_ms = timestamp
        result = self._landmarker.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb), timestamp)
        del rgb
        worlds = result.hand_world_landmarks or []
        hands = []
        for index, (landmarks, handedness) in enumerate(zip(result.hand_landmarks or [], result.handedness or [])):
            label = handedness[0].category_name if handedness else 'Unknown'
            score = handedness[0].score if handedness else 0.0
            world = [(-p.x, p.y, p.z) for p in worlds[index]] if index < len(worlds) else None
            hands.append((label, [(1.0 - p.x, p.y, p.z) for p in landmarks], score, world))
        return hands

    def close(self):
        try:
            self._landmarker.close()
        except Exception:
            pass


class VisionService:
    def __init__(self, publisher, *, open_camera, make_hands, make_faces, presence_enabled=False,
                 clock=time.monotonic, speak=None):
        self.publisher = publisher
        self._open_camera = open_camera
        self._make_hands = make_hands
        self._make_faces = make_faces
        self.presence_enabled = presence_enabled
        self.clock = clock
        self.speak = speak
        self.gesture = False
        self.camera = None
        self.camera_mode = None
        self.hands = None
        self.faces = None
        self.tracker = GestureTracker()
        self.presence = PresenceTracker(rate_hz=PRESENCE_RATE_HZ)
        self.error = None
        self.aspect = None  # of the current camera picture, once a frame arrives
        self.wake = asyncio.Event()

    # ---- control --------------------------------------------------------
    def state(self):
        return {'gesture': self.gesture, 'presence': self.presence_enabled,
                'camera': self.camera is not None, 'error': self.error}

    def control(self, command, source='unknown'):
        """Apply a control command; returns the new state. Unknown commands change nothing."""
        if command not in COMMANDS:
            return self.state()
        wanted = {'gesture_on': True, 'gesture_off': False,
                  'gesture_toggle': not self.gesture}.get(command, self.gesture)
        if wanted != self.gesture:
            self.gesture = wanted
            self.error = None
            if wanted:
                self.tracker.reset(self.clock())
            logger.info('[VISION] Gesture mode %s (%s).', 'ON' if wanted else 'OFF', source)
            self._announce(source)
            self.wake.set()
        return self.state()

    def _announce(self, source):
        self.publisher.emit_raw(STATE_SUBJECT, {**self.state(), 'source': source})
        if self.speak and source in SPOKEN_SOURCES:
            self.speak('Gesture mode on. Show me your hands.' if self.gesture else 'Gesture mode off.')

    # ---- camera ---------------------------------------------------------
    def _ensure_camera(self, mode):
        if self.camera is not None and self.camera_mode == mode:
            return True
        self._release_camera()
        width, height = gesture_resolution() if mode == 'gesture' else (FRAME_WIDTH, FRAME_HEIGHT)
        try:
            self.camera = self._open_camera(width, height)
            self.camera_mode = mode
            return True
        except Exception as error:
            self.error = str(error)[:200]
            logger.error('[VISION] %s', self.error)
            if mode == 'gesture':
                self.gesture = False
                self._announce('error')
            return False

    def _release_camera(self):
        if self.camera is not None:
            try:
                self.camera.release()
            finally:
                self.camera = None
                self.camera_mode = None
                self.aspect = None
                logger.info('[VISION] Camera released.')

    def close(self):
        self._release_camera()
        if self.hands is not None:
            self.hands.close()
            self.hands = None

    # ---- one step of the loop ------------------------------------------
    async def step(self):
        """Process one frame in the current mode. Returns seconds to wait before the next."""
        if self.gesture:
            return await self._gesture_step()
        if self.presence_enabled:
            return await self._presence_step()
        self._release_camera()
        return None  # idle: wait for a control command

    async def _gesture_step(self):
        started = self.clock()
        if not self._ensure_camera('gesture'):
            return 0.5
        if self.hands is None:
            try:
                self.hands = await asyncio.to_thread(self._make_hands)
            except Exception as error:
                self.error = f'Hand tracking unavailable: {str(error)[:160]}'
                logger.error('[VISION] %s', self.error)
                self.gesture = False
                self._announce('error')
                return 0.0
        ok, frame = await asyncio.to_thread(self.camera.read)
        detections = []
        if ok and frame is not None:
            height, width = frame.shape[:2]
            if self.aspect is None:
                logger.info('[VISION] Camera delivers %dx%d for hand tracking.', width, height)
            self.aspect = round(width / height, 4) if height else None
            # detect() mirrors the coordinates, not the picture (see MediaPipeHands).
            detections = await asyncio.to_thread(self.hands.detect, frame, self.clock())
            del frame
        now = self.clock()
        events = self.tracker.update(detections, now)
        # aspect (width / height) lets the UI keep hands in proportion.
        self.publisher.emit('hands', {'hands': self.tracker.snapshot(), 'aspect': self.aspect or 16 / 9})
        for event in events:
            if event['type'] in ('exit', 'idle'):
                self.control('gesture_off', 'gesture' if event['type'] == 'exit' else 'idle')
            self.publisher.emit('gesture', event)
        return max(0.0, 1.0 / GESTURE_RATE_HZ - (self.clock() - started))

    async def _presence_step(self):
        started = self.clock()
        if not self._ensure_camera('presence'):
            return 5.0
        if self.faces is None:
            self.faces = self._make_faces()
        ok, frame = await asyncio.to_thread(self.camera.read)
        box = None
        if ok and frame is not None:
            box = largest_face(await asyncio.to_thread(self.faces, frame))
            del frame
        payload = self.presence.update(box, FRAME_WIDTH, FRAME_HEIGHT, self.clock())
        if payload is not None:
            self.publisher.emit('gaze', payload)
        return max(0.0, 1.0 / PRESENCE_RATE_HZ - (self.clock() - started))

    async def run(self):
        while True:
            delay = await self.step()
            if delay is None:
                self.wake.clear()
                await self.wake.wait()
            else:
                await asyncio.sleep(delay)


class BusPublisher(SignalPublisher):
    """Signal publisher that can also publish to a full subject (vision state)."""

    def emit_raw(self, subject, payload):
        if not getattr(self.nc, 'is_connected', False):
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        task = loop.create_task(self._publish(subject, json.dumps(payload, separators=(',', ':')).encode()))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return True


def gesture_resolution():
    """Requested camera size for hand tracking: ULTRON_GESTURE_RESOLUTION=WxH or 1280x720."""
    value = os.getenv('ULTRON_GESTURE_RESOLUTION', '').strip().lower()
    try:
        width, height = (int(part) for part in value.split('x'))
        if 320 <= width <= 3840 and 240 <= height <= 2160:
            return width, height
    except ValueError:
        pass
    return GESTURE_WIDTH, GESTURE_HEIGHT


def open_camera_at(width, height):
    import cv2
    index = int(os.getenv('ULTRON_CAMERA_INDEX', '0'))
    backend = cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY
    capture = cv2.VideoCapture(index, backend)
    if not capture.isOpened():
        raise RuntimeError(f'Camera {index} could not be opened (in use, missing, or blocked by privacy settings).')
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FPS, 30)
    return capture


async def main():
    from nats.aio.client import Client as NATS
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    nc = NATS()
    await nc.connect(os.getenv('NATS_URL', 'nats://127.0.0.1:4222'), max_reconnect_attempts=-1,
                     reconnect_time_wait=2)
    publisher = BusPublisher(nc)

    def speak(text):
        publisher.emit_raw('ultron.voice', {'text': text, 'speech': text})

    service = VisionService(
        publisher,
        open_camera=open_camera_at,
        make_hands=MediaPipeHands,
        make_faces=face_detector,
        presence_enabled=os.getenv('ULTRON_PRESENCE', '').strip() == '1',
        speak=speak,
    )

    async def on_control(msg):
        try:
            data = json.loads(msg.data.decode())
        except (ValueError, UnicodeError):
            data = {}
        command = data.get('command') if isinstance(data, dict) else None
        source = str(data.get('source', 'unknown'))[:20] if isinstance(data, dict) else 'unknown'
        state = service.control(command, source)
        if msg.reply:
            await nc.publish(msg.reply, json.dumps(state).encode())

    await nc.subscribe(CONTROL_SUBJECT, cb=on_control)
    heartbeat = asyncio.create_task(heartbeat_loop(nc, 'vision'))
    logger.info('[VISION] Ready. Camera stays off until gesture mode is turned on%s. '
                'Frames are never stored or sent.', ' (presence on)' if service.presence_enabled else '')
    publisher.emit_raw(STATE_SUBJECT, {**service.state(), 'source': 'startup'})
    try:
        await service.run()
    finally:
        heartbeat.cancel()
        service.close()
        await nc.drain()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
