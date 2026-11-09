import type { UltronMode } from '../state/entityState.ts'
// Explicit extension so Node's test runner can load this module directly.
import { RING_COUNT } from './entityConfig.ts'

/* =========================================================
   ENTITY MOOD
   Physical "body language" for the entity, driven by heavy,
   slightly under-damped springs so every change overshoots a
   little and settles, the way real masses do. Also schedules
   the events that make it feel alive:
     - shockwaves on meaningful state changes
     - rare idle "thoughts" (a neural cascade + a ring twitch)
     - a slow awakening when the UI first opens
   All of this is a handful of numbers on the CPU per frame;
   the GPU layers just read the results as uniforms.
   ========================================================= */

export type Shape = {
  core: number // particle core scale
  cage: number // ring + arc cage scale
  shell: number // neural shell scale
  align: number // 0 = free gyroscope, 1 = rings locked into one plane
  spin: number // ring spin multiplier
  flow: number // fluid motion strength in the core
}

export const SHAPES: Record<UltronMode, Shape> = {
  offline: { core: 0.5, cage: 0.7, shell: 0.85, align: 0, spin: 0.2, flow: 0.1 },
  sleep: { core: 0.62, cage: 0.78, shell: 0.9, align: 0, spin: 0.3, flow: 0.2 },
  starting: { core: 0.9, cage: 0.95, shell: 0.98, align: 0.1, spin: 0.9, flow: 0.5 },
  idle: { core: 1, cage: 1, shell: 1, align: 0, spin: 1, flow: 0.55 },
  // Draws in slightly: attentive.
  listening: { core: 0.94, cage: 0.95, shell: 0.97, align: 0.12, spin: 1.35, flow: 0.7 },
  // Expands, layers separate.
  thinking: { core: 1.06, cage: 1.17, shell: 1.08, align: 0, spin: 1.7, flow: 1.15 },
  // Compresses; rings lock together and spin like a turbine.
  executing: { core: 0.9, cage: 0.9, shell: 1.0, align: 0.88, spin: 3.2, flow: 0.8 },
  alert: { core: 1.1, cage: 1.06, shell: 1.05, align: 0.3, spin: 2.2, flow: 1.4 },
  focus: { core: 1, cage: 1.05, shell: 1.02, align: 0.4, spin: 1.5, flow: 0.85 },
}

/** Shockwave strength when entering a mode (the wake word is "listening"). */
export const SHOCK_ON_ENTER: Partial<Record<UltronMode, number>> = {
  listening: 0.9,
  executing: 0.75,
  alert: 1.2,
}

/** Softer wave released when work finishes and the entity returns to idle. */
export const SHOCK_ON_FINISH = 0.6

// "Long ago": keeps event maths finite on the GPU (no Infinity in uniforms).
export const NO_EVENT = 1e4

const AWAKEN_DELAY = 1.2
const AWAKEN_SHOCK = 1.1

export class Spring {
  value: number
  velocity = 0
  stiffness: number
  damping: number

  constructor(value: number, stiffness: number, damping: number) {
    this.value = value
    this.stiffness = stiffness
    this.damping = damping
  }

  step(target: number, dt: number) {
    // Semi-implicit Euler: stable for these stiffnesses at frame-sized steps.
    const force = this.stiffness * (target - this.value) - this.damping * this.velocity
    this.velocity += force * dt
    this.value += this.velocity * dt
    return this.value
  }

  kick(impulse: number) {
    this.velocity += impulse
  }
}

export type MoodOptions = {
  ringCount?: number
  /** Source of randomness in [0, 1). Injected so tests are deterministic. */
  random?: () => number
  /** Softer, rarer motion for people who ask their OS to reduce motion. */
  reducedMotion?: boolean
}

export type MoodState = ReturnType<typeof createMood>['state']

export function createMood({ ringCount = RING_COUNT, random = Math.random, reducedMotion = false }: MoodOptions = {}) {
  // Heavy and slow: gentle, menacing. Damping ratio ~0.45 gives one soft overshoot.
  const heavy = (value: number) => new Spring(value, 5, 2)
  const shape = {
    core: heavy(0.15),
    cage: heavy(0.35),
    shell: heavy(0.6),
    align: heavy(0),
    spin: heavy(0.2),
    flow: heavy(0.3),
  }
  // Two small tilt offsets per ring: they wobble after a kick and settle.
  const wobble = Array.from({ length: ringCount }, () => [new Spring(0, 9, 1.2), new Spring(0, 9, 1.2)])
  const motionScale = reducedMotion ? 0.35 : 1

  const state = {
    core: shape.core.value,
    cage: shape.cage.value,
    shell: shape.shell.value,
    align: 0,
    spin: shape.spin.value,
    flow: shape.flow.value,
    ringAngle: new Array<number>(ringCount).fill(0),
    ringWobble: wobble.map(() => [0, 0] as [number, number]),
    shock: { age: NO_EVENT, strength: 0 },
    thought: { age: NO_EVENT, strength: 0, x: 0, y: 1, z: 0 },
  }

  let lastMode: UltronMode | null = null
  let elapsed = 0
  let nextThought = 6
  let awakened = false

  function shockwave(strength: number) {
    state.shock = { age: 0, strength: strength * motionScale }
    for (const pair of wobble) {
      pair[0].kick((random() - 0.5) * 0.9 * strength * motionScale)
      pair[1].kick((random() - 0.5) * 0.9 * strength * motionScale)
    }
  }

  function thought(strength: number) {
    // A uniformly random point on the sphere where the cascade starts.
    const z = random() * 2 - 1
    const angle = random() * Math.PI * 2
    const ring = Math.sqrt(1 - z * z)
    state.thought = { age: 0, strength: strength * motionScale, x: Math.cos(angle) * ring, y: z, z: Math.sin(angle) * ring }
    if (ringCount > 0) wobble[Math.floor(random() * ringCount)][0].kick((random() - 0.5) * 0.6 * strength * motionScale)
  }

  /** Advance by dt seconds of real time in the given mode. */
  function update(mode: UltronMode, dt: number) {
    elapsed += dt

    // Awakening: everything starts collapsed and unfolds, then a first pulse.
    if (!awakened && elapsed > AWAKEN_DELAY) {
      awakened = true
      shockwave(AWAKEN_SHOCK)
    }

    if (lastMode !== null && mode !== lastMode) {
      const enter = SHOCK_ON_ENTER[mode]
      const finished = mode === 'idle' && (lastMode === 'executing' || lastMode === 'thinking')
      if (enter) shockwave(enter)
      else if (finished) shockwave(SHOCK_ON_FINISH)
    }
    lastMode = mode

    const target = SHAPES[mode]
    state.core = shape.core.step(target.core, dt)
    state.cage = shape.cage.step(target.cage, dt)
    state.shell = shape.shell.step(target.shell, dt)
    state.align = Math.max(0, Math.min(1, shape.align.step(target.align, dt)))
    state.spin = shape.spin.step(target.spin, dt)
    state.flow = shape.flow.step(target.flow, dt)

    wobble.forEach((pair, i) => {
      state.ringWobble[i][0] = pair[0].step(0, dt)
      state.ringWobble[i][1] = pair[1].step(0, dt)
    })

    state.shock.age += dt
    state.thought.age += dt

    // Rare idle thoughts; more frequent while thinking, almost none asleep.
    nextThought -= dt
    if (nextThought <= 0) {
      const busy = mode === 'thinking' || mode === 'focus'
      const asleep = mode === 'sleep' || mode === 'offline'
      if (!asleep || random() < 0.25) thought(busy ? 1 : 0.7)
      const gap = busy ? 1.5 + random() * 2.5 : asleep ? 12 + random() * 10 : 3.5 + random() * 4
      nextThought = gap / motionScale
    }
  }

  /** Advance each ring's spin angle (radians) by its base speed × the mood's spin. */
  function spinRings(speeds: readonly number[], dt: number) {
    for (let i = 0; i < ringCount; i++) state.ringAngle[i] += (speeds[i] ?? 0) * state.spin * dt
  }

  return { state, update, spinRings }
}

function prefersReducedMotion() {
  try {
    return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

const engine = createMood({ reducedMotion: prefersReducedMotion() })

/** The live mood the entity layers read each frame. */
export const mood = engine.state
export const updateMood = engine.update
export const spinRings = engine.spinRings
