import type { UltronMode } from '../state/entityState.ts'

/* =========================================================
   CINEMA
   Decides when the film-style effects happen; the lens pass
   (EntityGlow) and the lightning layer just read the values.

     glitch    → signal corruption: on failures and alerts, and a
                 rare, brief flicker even when idle (menacing, never
                 frequent)
     scan      → a hologram scan line sweeps the frame now and then
     lightning → electric arcs while thinking or while the model works

   Plain numbers only, so it is unit tested with Node.
   ========================================================= */

export type CinemaInputs = {
  mode: UltronMode
  /** 0..1 model activity from liveSignals. */
  model: number
  /** True on the frame a task step is reported as failed. */
  stepFailed: boolean
}

const GLITCH_DECAY = 7 // per second: a burst lasts a fraction of a second
const SCAN_DURATION = 2.4 // seconds for one sweep top to bottom

export function createCinema(random: () => number = Math.random, reducedMotion = false) {
  const state = {
    glitch: 0,
    /** Scan line position: 1.15 (above the frame) → -0.15 (below); outside = hidden. */
    scan: -1,
    lightning: 0,
  }
  let lastMode: UltronMode | null = null
  let nextMicroGlitch = 25 + random() * 20
  let nextScan = 6 + random() * 6
  let scanAge = Infinity
  const scale = reducedMotion ? 0.3 : 1

  function burst(strength: number) {
    state.glitch = Math.max(state.glitch, strength * scale)
  }

  function update(dt: number, { mode, model, stepFailed }: CinemaInputs) {
    if (stepFailed) burst(1)
    if (mode !== lastMode && mode === 'alert') burst(0.8)
    lastMode = mode

    // A rare, brief flicker even when nothing is wrong: it is watching.
    nextMicroGlitch -= dt
    if (nextMicroGlitch <= 0) {
      if (mode !== 'sleep' && mode !== 'offline') burst(0.22 + random() * 0.12)
      nextMicroGlitch = 25 + random() * 25
    }
    state.glitch *= Math.exp(-GLITCH_DECAY * dt)
    if (state.glitch < 0.002) state.glitch = 0

    // Hologram scan: an occasional sweep, more often while busy.
    nextScan -= dt
    if (nextScan <= 0 && scanAge > SCAN_DURATION) {
      scanAge = 0
      const busy = mode === 'thinking' || mode === 'executing' || model > 0.1
      nextScan = busy ? 4 + random() * 3 : 9 + random() * 7
    }
    scanAge += dt
    state.scan = scanAge <= SCAN_DURATION ? 1.15 - (scanAge / SCAN_DURATION) * 1.3 : -1

    // Lightning follows thinking and real model work, eased so it fades in and out.
    const thinking = mode === 'thinking' || mode === 'focus' ? 0.65 : mode === 'alert' ? 0.45 : 0
    const target = Math.min(1, thinking + model * 0.6) * scale
    state.lightning += (target - state.lightning) * (1 - Math.exp(-3 * dt))
  }

  return { state, update, burst }
}
