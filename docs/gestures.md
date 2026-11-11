# Hand gestures

Control ULTRON with your hands through the webcam, Stark-style. This page is the
place to look up what each gesture does. The mappings live in
[`config/gestures.json`](../config/gestures.json); the tests check that this table
and that file agree, so this page is always current.

## Turning gesture mode on and off

The camera stays **closed** until gesture mode is turned on.

| On | Off |
| --- | --- |
| **Double clap** (two sharp claps, 0.15-0.8 s apart) | **Both palms** toward the camera for 1 second |
| Say **"Ultron, gesture mode"** / "turn on gesture mode" / "activate gestures" / "show my hands" | Say **"Ultron, gesture mode off"** / "stop gestures" / "exit gesture mode" |
| **Gesture mode** button in the Ops panel | The same button |
| | Automatically after 3 minutes with no hands in view |

A double clap toggles: clap twice again to turn it off. Set `ULTRON_CLAP=0` in `.env`
to disable clap detection. While gesture mode is on, the UI shows **GESTURE MODE**
with the pose it recognises, and draws your hands in front of the entity as fine
flowing particles in the entity's colour, with a targeting reticle on your right
index fingertip that tightens as you pinch.

## What works today

Gesture mode, the hand display, pose recognition and **both palms to exit** work
now. Every other row in the table below is recognised and shown but **does nothing
yet**: its action goes live in the stage listed (air mouse in G2, windows in G3,
the rest in G4).

## Mapping table

Your main hand is the **right** hand (`dominant_hand` in the config). "both" means
a two-handed gesture. **Stage** is the build step in which the action goes live; until
then the gesture is recognised and shown but does nothing.

| Gesture | Hands | Action | Stage | What it does |
| --- | --- | --- | --- | --- |
| `point` | dominant | `pointer.move` | G2 | Move the mouse pointer (air mouse) |
| `pinch_tap` | dominant | `pointer.click` | G2 | Click |
| `double_pinch` | dominant | `pointer.double_click` | G2 | Double-click |
| `pinch_hold` | dominant | `pointer.drag` | G2 | Drag while held |
| `two_finger_scroll` | dominant | `pointer.scroll` | G2 | Scroll (victory sign moved up or down) |
| `grab_move` | dominant | `window.move` | G3 | Pinch a window's title bar and move it |
| `grab_throw` | dominant | `window.throw` | G3 | Throw the grabbed window to the monitor in that direction |
| `two_hand_stretch` | both | `window.resize` | G3 | Pinch with both hands and pull apart / together to enlarge / shrink |
| `grab_release` | dominant | `clipboard.copy_paste` | G4 | Grab over a selection to copy, release where you want to paste |
| `swipe_left` | dominant | `media.previous` | G4 | Previous (track, tab or page) |
| `swipe_right` | dominant | `media.next` | G4 | Next (track, tab or page) |
| `twist` | dominant | `volume.adjust` | G4 | Turn like a knob: volume up / down |
| `palm_hold` | dominant | `media.play_pause` | G4 | Hold an open palm: pause / play |
| `frame` | both | `screen.screenshot` | G4 | Make a frame with both hands: screenshot |
| `fist_hold` | dominant | `system.lock` | G4 | Hold a fist for 2 s: lock the PC (asks to confirm) |
| `both_palms` | both | `gesture.exit` | G1 | Both palms to the camera for 1 s: leave gesture mode |
| `both_palms_push` | both | `system.stop` | G4 | Both palms pushed toward the camera: STOP everything (Ops Stop) |

To change a mapping, edit `config/gestures.json` (and this table) and restart the
vision service. Unknown gestures or actions are refused at startup, and
`system.lock` always asks for confirmation whatever the file says.

## Hand poses the engine recognises

`open_palm`, `fist`, `point` (index only), `pinch` (thumb on index), `victory`
(index + middle), `three`, `thumbs_up`, `thumbs_down`, `ok`, `rock` (index + pinky).
Movement gestures (taps, holds, swipes, twist, stretch, throw) are built from these
over time in the later stages.

## Multiple monitors

Throwing a window (`grab_throw`, stage G3) uses the real monitor layout Windows
reports (each screen's position and size), so it works for any arrangement: side by
side in either order, stacked, or offset, and for any number of screens. The window
goes to the nearest monitor in the direction of the throw. Example: a laptop on the
left and a 4K monitor on the right.

## Safety and accuracy rules

- **Engagement:** a hand counts only when it is fully in the picture and close
  enough to the camera, at any height. A hand cut off by the frame edge, or far
  away, is shown dimmed and never triggers anything.
- **No guessing:** fingers are judged from MediaPipe's 3D landmarks (real joint
  angles in metres, so distance and hand rotation do not matter). Straight fingers
  bend under 70°, curled ones over 100° (measured on real hands: 21-42° and
  119-195°). A finger in between is "unclear" and the pose is reported as unknown
  rather than guessed.
- **Left and right:** taken from MediaPipe on the normal camera picture (verified
  on MediaPipe's own left- and right-hand test photos). If both hands get the same
  label, the one on the right of the mirrored picture is your right hand; a single
  hand keeps its side while it moves.
- **Confirmation frames:** a pose must be seen for 3 consecutive frames (~0.1 s) to
  start and 4 to end, so one bad frame never fires anything.
- **Smoothing:** a One Euro filter steadies webcam jitter without lagging fast moves.
- **Actions go through ULTRON's checks:** gesture actions (from stage G2) use the same
  capability broker, policy and audit as voice commands. There is no separate
  "anything goes" path. Risky actions ask to confirm.
- **Separate from the old experiment:** gesture mode uses `ultron.signal.hands`,
  `ultron.signal.gesture` and `ultron.vision.*`. It never publishes on
  `ultron.gestures`, the channel where the experimental `tools/experimental/gesture.py`
  can lock the PC.

## Privacy and cost

- Frames are mirrored, analysed and discarded. Nothing is stored, logged or sent.
  Only landmark coordinates (21 points per hand) and pose names leave the vision
  service, and only to the local message bus.
- Hand tracking uses MediaPipe's bundled `assets/models/hand_landmarker.task`, about
  20-30 ms per frame on one CPU core. Gesture mode runs at about 30 frames a second
  and stops using the camera and CPU completely when switched off.
- Hand tracking asks the camera for 1280x720 (16:9). Most laptop webcams are 16:9;
  asking for 4:3 makes the driver crop the sides, so hands vanished before the edge
  of the real view. Set `ULTRON_GESTURE_RESOLUTION=WxH` in `.env` for another size;
  the vision window logs the size the camera actually delivers. On screen, the
  camera picture is spread over the whole window, so a hand can go anywhere the
  camera sees, and keeps its true shape.
- Webcam tracking has 50-100 ms of delay and needs reasonable light. It is ideal for
  grabbing, throwing, zooming, swiping and clicking large targets, not for pixel-exact
  pointing.

## Future: holographic display

The UI already renders glowing visuals on black, which is what Pepper's-ghost
pyramids and projectors need. A hologram output mode (four mirrored views) is planned.
