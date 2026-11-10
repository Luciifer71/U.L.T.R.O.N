"""Face-presence helpers for the vision service (``vision_service.py``).

With ``ULTRON_PRESENCE=1`` the vision service checks for a face 10 times a second
at low resolution so the entity can notice you sit down. These helpers find the
largest face (OpenCV YuNet, bundled model; Haar cascade fallback) and decide what
to publish on ``ultron.signal.gaze``: only whether someone is present and where.

Privacy: frames are discarded after detection; no image, crop or identity is ever
stored, logged or sent.
"""
from pathlib import Path


FRAME_WIDTH = 320
FRAME_HEIGHT = 240
RATE_HZ = 10.0
ABSENT_AFTER_SEC = 1.5  # no face for this long → nobody present
PRESENT_AFTER_FRAMES = 2  # consecutive detections before announcing presence
SMOOTHING = 0.45  # weight of the newest position (exponential moving average)
# OpenCV Zoo YuNet face detector (MIT licence, see assets/models/face_detection_yunet_LICENSE.txt).
YUNET_MODEL = 'face_detection_yunet_2023mar.onnx'



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
