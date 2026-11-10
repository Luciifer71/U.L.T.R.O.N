# Camera presence (optional)

With camera presence on, the visual entity notices you: when you sit down after
being away for a few seconds it reacts with a shockwave. It no longer turns or
drifts to follow you.

**It is off by default.** Nothing touches the camera unless you turn it on.

Presence is one mode of the **vision service**, the only ULTRON process that opens
the camera. Its other mode is hand-gesture control ([hand gestures](gestures.md)),
which only opens the camera while gesture mode is on. While gesture mode runs,
presence checks pause; they resume when it ends.

## Turn it on

Any one of:

```powershell
.\start-ultron.cmd --presence          # this launch only
.\.venv\Scripts\python.exe .\run_ultron.py presence   # just the vision service, presence on
```

or add `ULTRON_PRESENCE=1` to `.env` to have it on every time. The vision service
itself always starts with the other components but keeps the camera closed unless
presence or gesture mode is on. Use `ULTRON_CAMERA_INDEX=1` (or 2, …) to choose a
different camera. Stop it with Ctrl+C in its window; the camera is released
immediately.

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
([visual signals](visual-signals.md)). If the camera stops, the entity treats you as
away within 2 seconds.

Windows shows its camera-in-use indicator while presence runs. Camera access can
also be blocked for desktop apps in Windows Settings → Privacy & security → Camera.
