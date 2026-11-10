// Explicit extension so Node's test runner can load this module directly.
import type { TrackedHand } from './liveSignals.ts'

/* =========================================================
   HOLO HANDS (pure maths)
   Maps the vision service's hand landmarks (image-normalised,
   already mirrored) into the scene in front of the entity, and
   writes them into flat GPU buffers. No three.js here, so it
   is unit tested directly.
   ========================================================= */

/** Skeleton bones (pairs of landmark indices), same as src/ultron/gestures/hands.py. */
export const HAND_CONNECTIONS: readonly (readonly [number, number])[] = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [0, 17], [17, 18], [18, 19], [19, 20],
]

export const MAX_HANDS = 2
export const JOINTS = 21
export const FINGERTIPS = new Set([4, 8, 12, 16, 20])
export const LINE_VERTICES = MAX_HANDS * HAND_CONNECTIONS.length * 2

// The camera picture (4:3) is laid over the view at this depth, in front of
// the entity and its rings, so the hands never pass behind the core.
const PLANE_Z = 1.25
const WIDTH = 4.0
const HEIGHT = 3.0
const DEPTH = 2.5

/** Image coordinates (x right, y down, z negative towards the camera) to scene space. */
export function toScene(point: readonly [number, number, number]): [number, number, number] {
  return [(point[0] - 0.5) * WIDTH, (0.5 - point[1]) * HEIGHT, PLANE_Z - point[2] * DEPTH]
}

export type HandBuffers = {
  /** Line endpoints, xyz per vertex. */
  linePositions: Float32Array
  /** Line brightness per vertex. */
  lineGlow: Float32Array
  /** Joint centres, xyz per joint. */
  jointPositions: Float32Array
  /** Joint brightness and size per joint. */
  jointGlow: Float32Array
}

export function createHandBuffers(): HandBuffers {
  return {
    linePositions: new Float32Array(LINE_VERTICES * 3),
    lineGlow: new Float32Array(LINE_VERTICES),
    jointPositions: new Float32Array(MAX_HANDS * JOINTS * 3),
    jointGlow: new Float32Array(MAX_HANDS * JOINTS * 2),
  }
}

/** How strongly a pinch is shown: 1 when thumb and index touch, 0 when apart. */
export function pinchGlow(pinch: number) {
  return Math.min(1, Math.max(0, (0.6 - pinch) / 0.35))
}

/**
 * Write one hand into slot 0 or 1. `fade` is 0..1 (hands fade in and out).
 * An engaged hand (raised into the control zone) shines brighter than one
 * that is only being watched.
 */
export function writeHand(buffers: HandBuffers, slot: number, hand: TrackedHand | null, fade: number) {
  const points = hand ? hand.points.map(toScene) : null
  const level = hand ? fade * (hand.engaged ? 1 : 0.45) : 0
  const pinch = hand ? pinchGlow(hand.pinch) : 0

  const lineBase = slot * HAND_CONNECTIONS.length * 2
  HAND_CONNECTIONS.forEach(([a, b], i) => {
    const v = lineBase + i * 2
    for (const [k, joint] of [[0, a], [1, b]] as const) {
      const p = points ? points[joint] : [0, 0, PLANE_Z]
      buffers.linePositions.set(p, (v + k) * 3)
      buffers.lineGlow[v + k] = level
    }
  })

  const jointBase = slot * JOINTS
  for (let j = 0; j < JOINTS; j++) {
    const p = points ? points[j] : [0, 0, PLANE_Z]
    buffers.jointPositions.set(p, (jointBase + j) * 3)
    const tip = FINGERTIPS.has(j)
    // Thumb and index tips flare as they pinch together.
    const flare = j === 4 || j === 8 ? pinch : 0
    buffers.jointGlow[(jointBase + j) * 2] = level * (tip ? 1.4 : 0.8) * (1 + flare * 1.5)
    buffers.jointGlow[(jointBase + j) * 2 + 1] = (tip ? 0.055 : 0.035) * (1 + flare * 0.8)
  }
}

/** Keep each side in a stable slot (Right → 0, Left → 1) so hands never swap mid-fade. */
export function slotOf(side: TrackedHand['side']) {
  return side === 'Right' ? 0 : 1
}
