# Camera presence (optional)

With camera presence on, the visual entity knows where you are. It slowly turns
toward you, its core drifts toward you like the pupil of an eye, and when you sit
down after being away for a few seconds it notices you with a shockwave.

**It is off by default.** Nothing touches the camera unless you start it.

## Turn it on

Any one of:

```powershell
.\start-ultron.cmd --presence          # this launch only
.\.venv\Scripts\python.exe .\run_ultron.py presence   # just the camera component
```

or add `ULTRON_PRESENCE=1` to `.env` to start it with the other components every
time. Use `ULTRON_CAMERA_INDEX=1` (or 2, …) to choose a different camera. Stop it
with Ctrl+C in its window; the camera is released immediately.

## What it does with the camera

- Reads frames at 320×240, 10 times a second.
- Finds the largest face with OpenCV's YuNet detector (a 230 KB model bundled in
  `assets/models/`, MIT licence; older OpenCV builds fall back to the Haar cascade).
- Publishes only `{present, x, y, near}` on `ultron.signal.gaze`: whether someone is
  there and where their face is (-1..1), plus apparent size. No identity, no
  recognition.
- **Never stores, logs or sends an image.** Each frame is discarded after detection.
- Cost: about 3 ms of one CPU core per check (about 3% of one core at 10 checks/s).

The UI treats the signal as display-only, like the other live signals
([visual signals](visual-signals.md)). If the camera stops, the entity returns to
neutral within 2 seconds.

Windows shows its camera-in-use indicator while presence runs. Camera access can
also be blocked for desktop apps in Windows Settings → Privacy & security → Camera.
