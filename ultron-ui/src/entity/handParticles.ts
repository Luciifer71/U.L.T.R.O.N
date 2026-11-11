// Explicit extension so Node's test runner can load this module directly.
import type { TrackedHand } from './liveSignals.ts'

/* =========================================================
   HAND PARTICLES (pure maths)
   Your hands in gesture mode are drawn as fine particles,
   like the entity itself. Each particle is tied once, at
   startup, to a bone, the palm or a fingertip of hand 0 or 1.
   Every frame only the 42 joint positions change; the GPU
   places each particle from them. Hands can reach the whole
   screen (see mapHand). No three.js here, so this
   is unit tested directly.
   ========================================================= */

/** Bones (pairs of landmark indices), same as src/ultron/gestures/hands.py. */
export const HAND_CONNECTIONS: readonly (readonly [number, number])[] = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
]

/** The palm as a fan of triangles (wrist, thumb base, finger bases). */
export const PALM_TRIANGLES: readonly (readonly [number, number, number])[] = [
  [0, 1, 5], [0, 5, 9], [0, 9, 13], [0, 13, 17],
]

export const FINGERTIPS = [4, 8, 12, 16, 20] as const
export const MAX_HANDS = 2
export const JOINTS = 21
export const PARTICLES_PER_HAND = 2600

/** What a particle is attached to. */
export const KIND = { bone: 0, palm: 1, tip: 2 } as const

// Share of particles: energy flowing along the bones, a faint palm, bright tips.
const BONE_SHARE = 0.66
const PALM_SHARE = 0.22

/** Depth of the hands: in front of the entity and its rings, never behind the core. */
export const PLANE_Z = 1.25
// Hands reach this share of the screen edge (a little margin keeps fingertips visible).
const REACH = 0.94
// Hand size: one camera-picture height in scene units is this share of the screen height.
const HAND_SCALE = 0.85
// MediaPipe depth is weak; keep a gentle sense of depth only.
const DEPTH_SCALE = 0.6

/** Half the visible width and height of the scene at the hands' depth. */
export type HandView = { halfWidth: number; halfHeight: number }

/** The view of a perspective camera at the hands' depth. */
export function handView(cameraZ: number, fovDegrees: number, aspect: number): HandView {
  const halfHeight = Math.max(0.1, cameraZ - PLANE_Z) * Math.tan((fovDegrees * Math.PI) / 360)
  return { halfWidth: halfHeight * aspect, halfHeight }
}

const CENTRE_JOINTS = [0, 5, 9, 13, 17]

/** Palm centre in image coordinates. */
export function palmCentre(points: readonly (readonly [number, number, number])[]): [number, number, number] {
  const c: [number, number, number] = [0, 0, 0]
  for (const j of CENTRE_JOINTS) for (let k = 0; k < 3; k++) c[k] += points[j][k] / CENTRE_JOINTS.length
  return c
}

/**
 * Image landmarks (mirrored, x right, y down, 0..1) to scene positions.
 *
 * Where the hand is uses the whole screen: the camera picture's edges map to the
 * screen's edges, whatever the two aspect ratios, so a hand can go anywhere the
 * camera sees. The hand's own shape is scaled the same in every direction (using
 * the camera's real aspect), so it is never stretched.
 */
export function mapHand(
  points: readonly (readonly [number, number, number])[],
  view: HandView,
  cameraAspect = 16 / 9,
): [number, number, number][] {
  const c = palmCentre(points)
  const x = (c[0] - 0.5) * 2 * view.halfWidth * REACH
  const y = (0.5 - c[1]) * 2 * view.halfHeight * REACH
  const k = 2 * view.halfHeight * HAND_SCALE // scene units per picture height
  return points.map((p) => [
    x + (p[0] - c[0]) * cameraAspect * k,
    y - (p[1] - c[1]) * k,
    PLANE_Z - (p[2] - c[2]) * cameraAspect * k * DEPTH_SCALE,
  ])
}

/** Keep each side in a stable slot (Right → 0, Left → 1) so hands never swap mid-fade. */
export function slotOf(side: TrackedHand['side']) {
  return side === 'Right' ? 0 : 1
}

/** How strongly a pinch is shown: 1 when thumb and index touch, 0 when apart. */
export function pinchGlow(pinch: number) {
  return Math.min(1, Math.max(0, (0.6 - pinch) / 0.35))
}

export type HandParticles = {
  count: number
  /** Per particle: joint a, joint b, joint c (indices into the 42 joints), kind. */
  joints: Float32Array
  /** Per particle: weights for a, b, c (bone: start position along the bone in b). */
  weights: Float32Array
  /** Per particle: seed 0..1, radius (scene units), flow speed, size 0..1. */
  params: Float32Array
}

/**
 * Lay out the particles of both hands once. Joint indices already include the
 * hand offset (hand 1 uses joints 21..41), so the shader needs no branching.
 */
export function buildHandParticles(perHand = PARTICLES_PER_HAND, random: () => number = Math.random): HandParticles {
  const count = perHand * MAX_HANDS
  const joints = new Float32Array(count * 4)
  const weights = new Float32Array(count * 4)
  const params = new Float32Array(count * 4)
  const bones = Math.round(perHand * BONE_SHARE)
  const palm = Math.round(perHand * PALM_SHARE)
  let i = 0
  for (let hand = 0; hand < MAX_HANDS; hand++) {
    const o = hand * JOINTS
    for (let k = 0; k < perHand; k++, i++) {
      const seed = random()
      if (k < bones) {
        const [a, b] = HAND_CONNECTIONS[Math.floor(random() * HAND_CONNECTIONS.length)]
        joints.set([o + a, o + b, o + b, KIND.bone], i * 4)
        weights.set([0, random(), 0, 0], i * 4) // start position along the bone
        params.set([seed, 0.006 + random() * 0.018, 0.35 + random() * 0.8, random()], i * 4)
      } else if (k < bones + palm) {
        const [a, b, c] = PALM_TRIANGLES[Math.floor(random() * PALM_TRIANGLES.length)]
        let u = random()
        let v = random()
        if (u + v > 1) {
          u = 1 - u
          v = 1 - v
        }
        joints.set([o + a, o + b, o + c, KIND.palm], i * 4)
        weights.set([1 - u - v, u, v, 0], i * 4)
        params.set([seed, 0.01 + random() * 0.02, 0, random() * 0.6], i * 4)
      } else {
        const tip = FINGERTIPS[Math.floor(random() * FINGERTIPS.length)]
        joints.set([o + tip, o + tip, o + tip, KIND.tip], i * 4)
        weights.set([1, 0, 0, 0], i * 4)
        params.set([seed, 0.004 + random() * 0.03, 1.5 + random() * 2, 0.4 + random() * 0.6], i * 4)
      }
    }
  }
  return { count, joints, weights, params }
}

/** Scene positions of one hand's 21 joints, written into `target` at the hand's slot. */
export function writeJoints(target: Float32Array, slot: number, hand: TrackedHand, view: HandView, cameraAspect?: number) {
  mapHand(hand.points, view, cameraAspect).forEach((point, j) => target.set(point, (slot * JOINTS + j) * 3))
}
