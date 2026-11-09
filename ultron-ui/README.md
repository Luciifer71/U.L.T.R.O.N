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
```

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

`App.tsx` currently mounts `WebGPUTest.tsx`. The scene includes a central core,
particles, circuits, a computational shell, information flow and energy effects.
The existing `RenderRuntime` performance controller is not mounted by that active
scene. Adaptive rendering is unfinished; this guide does not claim it is enabled.

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
