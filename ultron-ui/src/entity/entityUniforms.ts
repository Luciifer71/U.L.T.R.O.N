import * as THREE from 'three/webgpu'
import { float, instancedBufferAttribute, uniform, uv, vec3 } from 'three/tsl'
import { getEntityVisualState } from '../state/entityStore'

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
  const axis = new THREE.Vector3()
  const a = new THREE.Vector3()
  const b = new THREE.Vector3()
  const helper = new THREE.Vector3()
  for (let i = 0; i < count; i++) {
    axis.randomDirection()
    helper.set(Math.abs(axis.x) < 0.9 ? 1 : 0, Math.abs(axis.x) < 0.9 ? 0 : 1, 0)
    a.crossVectors(axis, helper).normalize()
    b.crossVectors(axis, a).normalize()
    u.set([a.x, a.y, a.z], i * 3)
    w.set([b.x, b.y, b.z], i * 3)
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

