# U.L.T.R.O.N. / visual interface

An experimental React/TypeScript particle scene built with Three.js, React Three
Fiber, WebGPU and TSL. It consumes `ultron.visual` events from the local NATS bus.
The UI does not run the brain or prove that a desktop action succeeded.

## Development

From the repository root:

```powershell
npm ci --prefix .\ultron-ui
npm run dev --prefix .\ultron-ui
```

This package includes the NATS browser client (`@nats-io/nats-core`). Open Vite's printed URL. Start the
backend separately using the [main setup guide](../README.md#run).
The default WebSocket endpoint is `ws://127.0.0.1:9222`; override it with
`VITE_ULTRON_NATS_WS_URL` when needed. Do not expose an unauthenticated NATS server
publicly.

```powershell
npm run build
npm run lint
npm test
```

`npm test` runs the unit tests in `tests/` with Node's built-in test runner (Node
22.18 or newer runs TypeScript directly; no extra test framework is installed). They
cover the mood engine (springs, shockwaves, idle thoughts, reduced motion), the ring
config and orbit maths, and the visual-event contract. GitHub Actions runs lint (with
warnings as errors), the type-checked build and the tests on every push.

`npm run lint` should report no warnings. Per-frame shader uniform updates inside
`useFrame` are standard React Three Fiber practice, so the `react/immutability`
rule is turned off for `src/scene/**` only (see `.oxlintrc.json`). The production
bundle is about 2 MB because it includes the WebGPU build of three.js; Vite's
large-chunk notice is expected and has little effect when served locally.

## Operations panel

Press `` ` `` (backtick) or the **Ops** button for the operations panel: current task,
transcript, a typed command box, component health, recent tasks and a **Stop**
button. See [operations dashboard](../docs/operations-dashboard.md).

## States and troubleshooting

The scene responds to listening, thinking, executing, alert and idle events.
Keyboard keys 1–7 exercise idle, listening, thinking, executing, alert, focus and
sleep locally. Keyboard animation alone does not verify the backend connection.

`App.tsx` mounts `EntityCanvas.tsx`, which renders the computational entity from
`src/scene/UltronEntity.tsx` and `src/entity/`:

| Layer | What it is |
| --- | --- |
| Particle core | ~26k particles, each on its own orbit around a white-hot centre |
| Gyroscope rings | 8 segmented rings (lines, dashes, tick bands), each spinning on its own tilted axis |
| Arc cage | 90 short arcs on spheres around the core, each spinning independently |
| Neural shell | ~280 nodes linked to their nearest neighbours, with pulses travelling along the links |
| Dust | faint sparks on wide orbits for depth |
| Glow | a bloom pass over the whole scene |

Every particle and arc position is computed in the vertex shader from one shared
"entity clock" (`src/entity/entityUniforms.ts`). Nothing depends on anything else and
there is no per-frame simulation pass, so cost stays low. Busy states speed the clock
up smoothly. Colours follow the ULTRON state: red idle, blue listening, red and blue
thinking, gold executing.

Body language (`src/entity/mood.ts`) uses heavy, slightly under-damped springs:

- **Shape per state:** listening draws in, thinking expands and separates the layers,
  executing compresses and swings the rings into one plane to spin like a turbine,
  sleep collapses to a dim ember.
- **Shockwaves:** a slow wave rolls outward on the wake word (listening), on starting
  and finishing a task, and on alerts. It pushes particles and lights each layer as
  it passes. Rings wobble a few degrees and settle.
- **Idle thoughts:** every few seconds (more while thinking, rarely asleep) a cascade
  of light spreads across the neural shell from a random point, and one ring twitches.
- **Fluid core:** a drifting noise field bends the core particles' orbits like smoke.
- **Awakening:** on load the entity starts collapsed, unfolds and releases a first pulse.
- **Depth:** the far half of the entity is dimmed so the glow reads as a 3D object.
- **Reduced motion:** if the operating system asks to reduce motion, shockwaves and
  wobble are softer and idle thoughts rarer; shape changes still show the state.

Live data (Phase B, see [visual signals](../docs/visual-signals.md)): each task step
lights its own ring (running, done, failed, skipped), your voice ripples the core,
the core swells while ULTRON speaks, words stream in and replies stream out
(`src/entity/DataStream.tsx`), neural cascades build while the model thinks, and real
CPU/memory strain heats the core and makes the rings shiver.

Cinematic finish (Phase C): the final frame goes through one lens pass
(`src/entity/EntityGlow.tsx`): light bends in a ring around the core, colours split
toward the edges, bright light throws a thin horizontal (anamorphic) streak, a vignette
and faint film grain sit on top, and an occasional hologram scan line sweeps the frame.
`src/entity/cinema.ts` decides when: a failed step or an alert glitches the image
(slice tearing and colour split for a fraction of a second), and a rare, brief flicker
happens even when idle. Electric arcs (`src/entity/Lightning.tsx`) strike from the core
to the ring cage while ULTRON thinks or the model works. Reduced motion softens all of it.

### Performance

The UI is built to stay light: rendering is capped at 60 fps (`?fps=30..240` to change),
every particle, arc and bolt is positioned in the vertex shader from a few shared values
(no per-particle simulation), the CPU does a handful of spring updates per frame, and the
lens pass adds one full-screen pass with about two dozen texture reads per pixel. Hidden
or minimised tabs stop rendering. On the backend, live signals cost one `psutil` read
every 2 s plus small messages while you speak or a task runs.

Camera presence (Phase D, optional, off by default; see
[camera presence](../docs/camera-presence.md)): the entity notices you arrive with a
shockwave.

Gesture mode (see [hand gestures](../docs/gestures.md)): your tracked hands appear in
front of the entity made of fine flowing particles in the entity's colour
(`src/entity/HoloHands.tsx`, layout in `src/entity/handParticles.ts`): energy streams
along each bone to the fingertips, and a targeting reticle on the right index
fingertip tightens as you pinch. A GESTURE MODE heading shows the latest pose
(`src/ops/GestureHud.tsx`). The Ops panel has a Gesture mode button and the vision
service's health. Each frame sends only 42 joint positions to the GPU (5,200
particles are placed there); nothing is drawn while gesture mode is off.

The earlier dot-field layers (`src/scene/TSL*.tsx`, `EnergyEvents.tsx`) are unchanged.
Open the UI with `?legacy=1` (for example `http://localhost:5173/?legacy=1`) to show
them instead. The `RenderRuntime` performance controller is still not mounted.

If animation stutters, record browser/version, display resolution, frame timing
and whether model/speech inference was active. If animation is smooth but fails
to react, inspect the browser console for `[ULTRON BUS]` connection/subscription
errors. Include relevant errors with a backend support report, without credentials.
A still screenshot cannot establish frame rate or GPU selection.

## Scope

Reported UI lag is unresolved. Backend Python checks do not validate this scene's
performance. Legacy scene files are retained while renderer behavior is investigated;
they are not evidence that every rendering path is active.

The repository's [ownership terms](../README.md#license--ownership) apply here too.
