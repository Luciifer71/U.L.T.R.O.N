import * as THREE from 'three/webgpu'
import { exp, float, instancedBufferAttribute, positionView, smoothstep, uniform, uv, vec3 } from 'three/tsl'
import type { Node } from 'three/webgpu'
import { getEntityVisualState } from '../state/entityStore'
import { getUltronEntityState } from '../simulation/entitySimulation'
import { mood, pulse, updateMood } from './mood'
import { liveSignals } from './liveSignals'
import { createCinema } from './cinema'
import { prefersReducedMotion } from './mood'
import { randomOrbitBasis } from './entityConfig'

/* =========================================================
   SHARED ENTITY UNIFORMS
   One set of GPU values, updated once per frame from the
   ULTRON visual state and read by every entity layer.

   Motion uses an accumulated "entity clock" instead of raw
   time. Each layer computes positions as a pure function of
   this clock, so no particle depends on any other and no
   per-frame simulation pass is needed. Speeding the clock up
   (listening / thinking / executing) can never make anything
   jump, because the clock only ever moves forward smoothly.
   ========================================================= */

export const entityUniforms = {
  clock: uniform(0),
  red: uniform(0.94),
  blue: uniform(0.05),
  gold: uniform(0.01),
  intensity: uniform(0.58),
  coreGlow: uniform(0.68),
  motion: uniform(0.25),
  turbulence: uniform(0.18),
  information: uniform(0.08),
  events: uniform(0.035),
  // Body language (see mood.ts): spring-driven scales and fluid strength.
  coreScale: uniform(0.15),
  cageScale: uniform(0.35),
  shellScale: uniform(0.6),
  flow: uniform(0.3),
  // Latest shockwave and idle "thought" (age in real seconds).
  shockAge: uniform(99),
  shockStrength: uniform(0),
  thoughtAge: uniform(99),
  thoughtStrength: uniform(0),
  thoughtDir: uniform(new THREE.Vector3(0, 1, 0)),
  // Live data (see liveSignals.ts), all 0..1, plus wall-clock seconds.
  voice: uniform(0),
  speak: uniform(0),
  model: uniform(0),
  pressure: uniform(0),
  now: uniform(0),
  // Film effects (see cinema.ts).
  glitch: uniform(0),
  scan: uniform(-1),
  lightning: uniform(0),
}

const cinema = createCinema(Math.random, prefersReducedMotion())
let failuresSeen = 0
let noticesSeen = 0
const NOTICE_SHOCK = 0.85

/** Camera distance to the entity centre (see EntityCanvas). */
export const CAMERA_DISTANCE = 4.8

/**
 * Additive glow has no occlusion, so the far side of the entity would be as
 * bright as the near side and the whole thing would read flat. Dimming the
 * far half gives a strong sense of depth for almost no cost.
 */
export function depthFade() {
  const distance = positionView.z.negate()
  return float(1).sub(smoothstep(CAMERA_DISTANCE - 0.6, CAMERA_DISTANCE + 1.9, distance).mul(0.55))
}

const SHOCK_SPEED = 0.95 // units per second: slow and heavy
const SHOCK_WIDTH = 0.16

/** Brightness/push of the current shockwave at a given distance from the centre (0..~1.5). */
export function shockAt(radius: Node<'float'>) {
  const u = entityUniforms
  const front = u.shockAge.mul(SHOCK_SPEED)
  const offset = radius.sub(front).div(SHOCK_WIDTH)
  return u.shockStrength.mul(exp(u.shockAge.mul(-0.9))).mul(exp(offset.mul(offset).negate()))
}

// Palette (linear, HDR-friendly). Bloom does the softening.
export const RED = vec3(1.0, 0.025, 0.045)
export const BLUE = vec3(0.015, 0.26, 1.0)
export const GOLD = vec3(1.0, 0.52, 0.06)

/** The current state colour: red idle, blue listening, mixed thinking, gold executing. */
export function stateColor() {
  const u = entityUniforms
  return RED.mul(u.red).add(BLUE.mul(u.blue)).add(GOLD.mul(u.gold))
}

let clockSeconds = 0

/** Call once per frame (before rendering) with the frame delta in seconds. */
export function syncEntityUniforms(dt: number) {
  const v = getEntityVisualState()
  const u = entityUniforms
  // Calm drift when idle, quicker when busy; never stops completely.
  clockSeconds += dt * (0.55 + v.motion * 1.1)
  u.clock.value = clockSeconds
  u.red.value = v.redWeight
  u.blue.value = v.blueWeight
  u.gold.value = v.goldWeight
  u.intensity.value = v.intensity
  u.coreGlow.value = v.coreGlow
  u.motion.value = v.motion
  u.turbulence.value = v.turbulence
  u.information.value = v.informationDensity
  u.events.value = v.eventDensity

  const now = performance.now() / 1000
  liveSignals.update(now, dt)
  const live = liveSignals.state
  u.voice.value = live.voice
  u.speak.value = live.speak
  u.model.value = live.model
  u.pressure.value = live.pressure
  u.now.value = now

  const mode = getUltronEntityState().mode
  updateMood(mode, dt, live.model)
  // Someone arrived in front of the camera after being away: it notices them.
  if (live.notices !== noticesSeen) {
    noticesSeen = live.notices
    pulse(NOTICE_SHOCK)
  }

  cinema.update(dt, { mode, model: live.model, stepFailed: live.failures !== failuresSeen })
  failuresSeen = live.failures
  u.glitch.value = cinema.state.glitch
  u.scan.value = cinema.state.scan
  u.lightning.value = cinema.state.lightning
  u.coreScale.value = mood.core
  u.cageScale.value = mood.cage
  u.shellScale.value = mood.shell
  u.flow.value = mood.flow
  u.shockAge.value = mood.shock.age
  u.shockStrength.value = mood.shock.strength
  u.thoughtAge.value = mood.thought.age
  u.thoughtStrength.value = mood.thought.strength
  ;(u.thoughtDir.value as THREE.Vector3).set(mood.thought.x, mood.thought.y, mood.thought.z)
  return clockSeconds
}

export const WHITE_HOT = vec3(1.0, 0.9, 0.82)

export function softDisc() {
  // 1 at the sprite centre, 0 at its edge, with a soft falloff.
  const d = uv().sub(0.5).length().mul(2.0)
  return float(1).sub(d).clamp(0, 1).pow(2.2)
}

/** Random orthonormal orbit basis (u, w) plus orbit parameters for each particle. */
export function buildOrbits(count: number, radius: (r: number) => number, speed: (r: number, s: number) => number) {
  const u = new Float32Array(count * 3)
  const w = new Float32Array(count * 3)
  const p = new Float32Array(count * 4)
  for (let i = 0; i < count; i++) {
    const basis = randomOrbitBasis()
    u.set(basis.u, i * 3)
    w.set(basis.w, i * 3)
    const r = radius(Math.random())
    const seed = Math.random()
    p.set([r, Math.random() * Math.PI * 2, speed(r, Math.random()), seed], i * 4)
  }
  return {
    u: instancedBufferAttribute<'vec3'>(new THREE.InstancedBufferAttribute(u, 3), 'vec3'),
    w: instancedBufferAttribute<'vec3'>(new THREE.InstancedBufferAttribute(w, 3), 'vec3'),
    p: instancedBufferAttribute<'vec4'>(new THREE.InstancedBufferAttribute(p, 4), 'vec4'),
  }
}

