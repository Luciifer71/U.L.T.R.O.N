import type { UltronMode } from '../state/entityState'

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

type Shape = {
  core: number // particle core scale
  cage: number // ring + arc cage scale
  shell: number // neural shell scale
  align: number // 0 = free gyroscope, 1 = rings locked into one plane
  spin: number // ring spin multiplier
  flow: number // fluid motion strength in the core
}

const SHAPES: Record<UltronMode, Shape> = {
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

class Spring {
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
    const force = this.stiffness * (target - this.value) - this.damping * this.velocity
    this.velocity += force * dt
    this.value += this.velocity * dt
    return this.value
  }
  kick(impulse: number) {
    this.velocity += impulse
  }
}

// Heavy and slow: gentle, menacing. Damping ratio ~0.45 gives one soft overshoot.
const heavy = (v: number) => new Spring(v, 5, 2)

export const RING_COUNT = 8

const shape = {
  core: heavy(0.15),
  cage: heavy(0.35),
  shell: heavy(0.6),
  align: heavy(0),
  spin: heavy(0.2),
  flow: heavy(0.3),
}

// Two small tilt offsets per ring: they wobble after a kick and settle.
const wobble = Array.from({ length: RING_COUNT }, () => [new Spring(0, 9, 1.2), new Spring(0, 9, 1.2)])
const ringAngle = new Array(RING_COUNT).fill(0)

export type Pulse = { age: number; strength: number }

export const mood = {
  core: 0.15,
  cage: 0.35,
  shell: 0.6,
  align: 0,
  spin: 0.2,
  flow: 0.3,
  ringAngle,
  ringWobble: wobble.map(() => [0, 0]),
  shock: { age: 99, strength: 0 } as Pulse,
  thought: { age: 99, strength: 0, x: 0, y: 1, z: 0 },
}

let lastMode: UltronMode | null = null
let elapsed = 0
let nextThought = 6
let awakened = false

const SHOCK_ON_ENTER: Partial<Record<UltronMode, number>> = {
  listening: 0.9, // wake word: it notices you
  executing: 0.75,
  alert: 1.2,
}

function shockwave(strength: number) {
  mood.shock = { age: 0, strength }
  for (const pair of wobble) {
    pair[0].kick((Math.random() - 0.5) * 0.9 * strength)
    pair[1].kick((Math.random() - 0.5) * 0.9 * strength)
  }
}

function thought(strength: number) {
  // A random point on the network where the cascade starts.
  const z = Math.random() * 2 - 1
  const a = Math.random() * Math.PI * 2
  const s = Math.sqrt(1 - z * z)
  mood.thought = { age: 0, strength, x: Math.cos(a) * s, y: z, z: Math.sin(a) * s }
  const ring = wobble[Math.floor(Math.random() * RING_COUNT)]
  ring[0].kick((Math.random() - 0.5) * 0.6 * strength)
}

/** Advance the mood by dt seconds of real time for the current mode. */
export function updateMood(mode: UltronMode, dt: number) {
  elapsed += dt

  // Awakening: everything starts collapsed and unfolds, then a first pulse.
  if (!awakened && elapsed > 1.2) {
    awakened = true
    shockwave(1.1)
  }

  if (lastMode !== null && mode !== lastMode) {
    const enter = SHOCK_ON_ENTER[mode]
    // Finishing a task (back to idle from work) releases a softer wave.
    const finished = mode === 'idle' && (lastMode === 'executing' || lastMode === 'thinking')
    if (enter) shockwave(enter)
    else if (finished) shockwave(0.6)
  }
  lastMode = mode

  const target = SHAPES[mode]
  mood.core = shape.core.step(target.core, dt)
  mood.cage = shape.cage.step(target.cage, dt)
  mood.shell = shape.shell.step(target.shell, dt)
  mood.align = Math.max(0, Math.min(1, shape.align.step(target.align, dt)))
  mood.spin = shape.spin.step(target.spin, dt)
  mood.flow = shape.flow.step(target.flow, dt)

  wobble.forEach((pair, i) => {
    mood.ringWobble[i][0] = pair[0].step(0, dt)
    mood.ringWobble[i][1] = pair[1].step(0, dt)
  })

  mood.shock.age += dt
  mood.thought.age += dt

  // Rare idle thoughts; more frequent while thinking, almost none asleep.
  nextThought -= dt
  if (nextThought <= 0) {
    const busy = mode === 'thinking' || mode === 'focus'
    const asleep = mode === 'sleep' || mode === 'offline'
    if (!asleep || Math.random() < 0.25) thought(busy ? 1 : 0.7)
    nextThought = busy ? 1.5 + Math.random() * 2.5 : asleep ? 12 + Math.random() * 10 : 3.5 + Math.random() * 4
  }
}

/** Advance each ring's own spin angle (radians) by its base speed. */
export function spinRings(speeds: number[], dt: number) {
  speeds.forEach((speed, i) => {
    ringAngle[i] += speed * mood.spin * dt
  })
}
