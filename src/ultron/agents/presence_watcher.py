"""Optional camera presence for the visual entity. Off unless explicitly started.

Reads the webcam at low resolution, finds the largest face with OpenCV's YuNet
detector (small bundled model, no download), and publishes only three numbers on
``ultron.signal.gaze``: whether someone is present and where their face is
(``x`` left/right and ``y`` up/down in -1..1, from the viewer's side).

Privacy: frames stay in memory for one detection and are then discarded. No image,
face crop or identity is stored, logged or sent. The camera is released on exit.
This is display-only: nothing acts on the signal except the UI.

Start it with ``run_ultron.py presence``, or ``start-ultron.cmd --presence``, or set
``ULTRON_PRESENCE=1`` in ``.env`` to start it with the other components.
"""
import asyncio
import logging
import os
import time
from pathlib import Path

from ultron.control.signals import SignalPublisher

FRAME_WIDTH = 320
FRAME_HEIGHT = 240
RATE_HZ = 10.0
ABSENT_AFTER_SEC = 1.5  # no face for this long → nobody present
PRESENT_AFTER_FRAMES = 2  # consecutive detections before announcing presence
SMOOTHING = 0.45  # weight of the newest position (exponential moving average)
# OpenCV Zoo YuNet face detector (MIT licence, see assets/models/face_detection_yunet_LICENSE.txt).
YUNET_MODEL = 'face_detection_yunet_2023mar.onnx'

logger = logging.getLogger('ultron.presence')


def largest_face(boxes):
    """The biggest (closest) face box (x, y, w, h), or None."""
    best = None
    for box in boxes if boxes is not None else ():
        x, y, w, h = (int(v) for v in box)
        if w <= 0 or h <= 0:
            continue
        if best is None or w * h > best[2] * best[3]:
            best = (x, y, w, h)
    return best


def gaze_from_box(box, frame_width, frame_height):
    """Face centre as viewer-side coordinates in -1..1, plus apparent size (0..1).

    The camera faces the user, so its image is mirrored: a face on the left of the
    camera frame is on the right of the screen. ``y`` is positive upward.
    """
    x, y, w, h = box
    cx = (x + w / 2) / frame_width
    cy = (y + h / 2) / frame_height
    gx = max(-1.0, min(1.0, 1.0 - 2.0 * cx))
    gy = max(-1.0, min(1.0, 1.0 - 2.0 * cy))
    near = max(0.0, min(1.0, w / frame_width))
    return gx, gy, near


class PresenceTracker:
    """Smooths detections and decides what to publish, at most ``rate_hz`` times a second."""

    def __init__(self, rate_hz=RATE_HZ, absent_after=ABSENT_AFTER_SEC, present_after=PRESENT_AFTER_FRAMES,
                 smoothing=SMOOTHING):
        self.interval = 1.0 / rate_hz
        self.absent_after = absent_after
        self.present_after = present_after
        self.smoothing = smoothing
        self.present = False
        self.streak = 0
        self.last_seen = -float('inf')
        self.last_sent = -float('inf')
        self.x = 0.0
        self.y = 0.0
        self.near = 0.0

    def update(self, box, frame_width, frame_height, now):
        """Feed one frame's largest face (or None). Returns a payload to publish, or None."""
        changed = False
        if box is not None:
            gx, gy, near = gaze_from_box(box, frame_width, frame_height)
            a = self.smoothing if self.streak else 1.0
            self.x += (gx - self.x) * a
            self.y += (gy - self.y) * a
            self.near += (near - self.near) * a
            self.streak += 1
            self.last_seen = now
            if not self.present and self.streak >= self.present_after:
                self.present = changed = True
        else:
            self.streak = 0
            if self.present and now - self.last_seen > self.absent_after:
                self.present = False
                changed = True
        if not changed and (not self.present or now - self.last_sent < self.interval):
            return None
        self.last_sent = now
        return {'present': self.present, 'x': round(self.x, 3), 'y': round(self.y, 3), 'near': round(self.near, 3)}


def open_camera(index):
    import cv2
    backend = cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY
    capture = cv2.VideoCapture(index, backend)
    if not capture.isOpened():
        raise RuntimeError(f'Camera {index} could not be opened (in use, missing, or blocked by privacy settings).')
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    return capture


def face_detector(model_path=None):
    """Return detect(frame) -> list of (x, y, w, h) face boxes.

    Uses OpenCV's YuNet detector (OpenCV 4.5.4+ and 5.x) with the bundled model,
    falling back to the classic Haar cascade on older OpenCV builds.
    """
    import cv2
    from ultron.paths import project_root
    path = Path(model_path) if model_path else project_root() / 'assets' / 'models' / YUNET_MODEL
    if hasattr(cv2, 'FaceDetectorYN') and path.is_file():
        net = cv2.FaceDetectorYN.create(str(path), '', (FRAME_WIDTH, FRAME_HEIGHT), 0.7, 0.3, 20)

        def detect(frame):
            height, width = frame.shape[:2]
            net.setInputSize((width, height))
            _, faces = net.detect(frame)
            return [] if faces is None else [tuple(float(v) for v in face[:4]) for face in faces]
        return detect

    if hasattr(cv2, 'CascadeClassifier'):
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        if not cascade.empty():
            def detect(frame):
                gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                return cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(36, 36))
            return detect
    raise RuntimeError(f'No face detector available: {YUNET_MODEL} is missing from assets/models '
                       'and this OpenCV build has no Haar cascade.')


async def run_presence(capture, detect, publisher, *, clock=time.monotonic, sleep=asyncio.sleep,
                       max_frames=None, tracker=None):
    """Read frames, detect, publish. Returns when ``max_frames`` is reached (tests) or on cancel."""
    tracker = tracker or PresenceTracker()
    frames = 0
    while max_frames is None or frames < max_frames:
        started = clock()
        ok, frame = await asyncio.to_thread(capture.read)
        frames += 1
        if ok and frame is not None:
            height, width = frame.shape[:2]
            box = largest_face(await asyncio.to_thread(detect, frame))
            payload = tracker.update(box, width, height, clock())
            if payload is not None:
                publisher.emit('gaze', payload)
            del frame  # nothing about the image outlives this iteration
        else:
            payload = tracker.update(None, FRAME_WIDTH, FRAME_HEIGHT, clock())
            if payload is not None:
                publisher.emit('gaze', payload)
        await sleep(max(0.0, 1.0 / RATE_HZ - (clock() - started)))


async def main():
    from nats.aio.client import Client as NATS
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    nc = NATS()
    await nc.connect(os.getenv('NATS_URL', 'nats://127.0.0.1:4222'), max_reconnect_attempts=-1,
                     reconnect_time_wait=2)
    publisher = SignalPublisher(nc)
    capture = open_camera(int(os.getenv('ULTRON_CAMERA_INDEX', '0')))
    logger.info('[PRESENCE] Camera on at %dx%d, %d checks/s. Only face position numbers are sent; '
                'no images are stored or transmitted. Stop with Ctrl+C.', FRAME_WIDTH, FRAME_HEIGHT, RATE_HZ)
    try:
        await run_presence(capture, face_detector(), publisher)
    finally:
        capture.release()
        publisher.emit('gaze', {'present': False, 'x': 0, 'y': 0, 'near': 0})
        await asyncio.sleep(0.1)
        await nc.drain()
        logger.info('[PRESENCE] Camera released.')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
