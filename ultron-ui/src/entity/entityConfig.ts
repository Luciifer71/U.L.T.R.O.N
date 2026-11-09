/* =========================================================
   ENTITY CONFIG
   Static layout shared by the renderer and the mood engine.
   Kept free of three.js so it can be unit tested with Node.
   ========================================================= */

export type RingKind = 'line' | 'band'

export type RingSpec = {
  kind: RingKind
  radius: number
  width: number // tube radius for lines, band width for bands
  count: number // segments around the ring (0 = continuous)
  duty: number // lit fraction of each segment
  spin: number // radians per second at the idle spin (scaled by the mood's spin)
  tilt: [number, number, number]
  brightness: number
  sweep: number // highlight sweep speed (turns per clock second)
}

export const RINGS: readonly RingSpec[] = [
  { kind: 'line', radius: 0.8, width: 0.0028, count: 0, duty: 1, spin: 0.35, tilt: [1.2, 0.2, 0], brightness: 1.0, sweep: 0.22 },
  { kind: 'band', radius: 0.9, width: 0.035, count: 120, duty: 0.2, spin: -0.22, tilt: [0.35, 1.1, 0.2], brightness: 0.55, sweep: 0.15 },
  { kind: 'line', radius: 1.0, width: 0.0024, count: 36, duty: 0.72, spin: 0.18, tilt: [-0.6, 0.4, 0.9], brightness: 0.9, sweep: -0.18 },
  { kind: 'band', radius: 1.08, width: 0.022, count: 6, duty: 0.62, spin: -0.12, tilt: [1.55, 0.0, 0.5], brightness: 0.75, sweep: 0.12 },
  { kind: 'line', radius: 1.18, width: 0.002, count: 90, duty: 0.45, spin: 0.1, tilt: [0.15, -0.9, -0.3], brightness: 0.7, sweep: 0.1 },
  { kind: 'band', radius: 1.27, width: 0.06, count: 240, duty: 0.1, spin: -0.07, tilt: [0.9, 0.7, -0.6], brightness: 0.45, sweep: -0.08 },
  { kind: 'line', radius: 1.38, width: 0.0022, count: 3, duty: 0.82, spin: 0.08, tilt: [-1.1, -0.3, 0.2], brightness: 0.8, sweep: 0.07 },
  { kind: 'line', radius: 1.5, width: 0.0016, count: 0, duty: 1, spin: -0.05, tilt: [0.5, 1.4, 0.9], brightness: 0.35, sweep: -0.05 },
]

export const RING_COUNT = RINGS.length

export type Vec3 = [number, number, number]

/**
 * A random orbit plane: two unit vectors u and w, perpendicular to each other
 * and to a uniformly random axis. A point on the orbit at angle a is
 * radius * (u cos a + w sin a).
 */
export function randomOrbitBasis(random: () => number = Math.random): { u: Vec3; w: Vec3 } {
  const z = random() * 2 - 1
  const t = random() * Math.PI * 2
  const s = Math.sqrt(1 - z * z)
  const axis: Vec3 = [Math.cos(t) * s, Math.sin(t) * s, z]
  // Any vector not parallel to the axis gives a perpendicular via the cross product.
  const helper: Vec3 = Math.abs(axis[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]
  const u = normalize(cross(axis, helper))
  const w = normalize(cross(axis, u))
  return { u, w }
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

function normalize(v: Vec3): Vec3 {
  const length = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / length, v[1] / length, v[2] / length]
}
