import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { MeshBasicNodeMaterial } from 'three/webgpu'
import { atan, float, floor, fract, mix, positionLocal, sin, smoothstep, step, uniform } from 'three/tsl'
import { depthFade, entityUniforms, RED, shockAt, stateColor, WHITE_HOT } from './entityUniforms'
import { kickRing, mood, spinRings } from './mood'
import { liveSignals, type RingStatus } from './liveSignals'
import { RINGS, type RingSpec } from './entityConfig'

/* =========================================================
   GYROSCOPE RINGS
   Thin luminous rings around the core, each made of
   segmented arcs, dashes or tick marks, each spinning on
   its own tilted axis. A bright highlight sweeps around
   every ring. All patterns are drawn in the fragment shader
   from the angle around the ring, so a ring costs one draw.

   Each ring can also carry one live task step (liveSignals):
     running → a fast bright pulse races around it
     done    → a white-gold flash, then it settles
     failed  → it turns red and its segments break and flicker
     skipped → it goes dim for a moment
   ========================================================= */

/** Per-ring live values, written on the CPU each frame. */
function createRingLive() {
  return { active: uniform(0), flash: uniform(0), fail: uniform(0), dim: uniform(0) }
}

type RingLive = ReturnType<typeof createRingLive>

function ringMaterial(spec: RingSpec, offset: number, live: RingLive) {
  const { clock, intensity, cageScale, now } = entityUniforms
  const material = new MeshBasicNodeMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  })
  material.toneMapped = false

  // 0..1 position around the ring.
  const around = atan(positionLocal.y, positionLocal.x).div(Math.PI * 2).add(0.5)

  // Segment mask: continuous, dashed arcs, or fine tick marks.
  const segment = spec.count > 0 ? step(fract(around.mul(spec.count)), float(spec.duty)) : float(1)

  // Bright head with a fading tail, sweeping around the ring.
  const head = fract(around.add(clock.mul(spec.sweep)).add(offset))
  const sweep = smoothstep(0.55, 1.0, head).pow(4.0).mul(2.4)

  // Bands fade at their inner/outer edge so they look like etched rings.
  const edge =
    spec.kind === 'band'
      ? float(1).sub(positionLocal.xy.length().sub(spec.radius).abs().div(spec.width / 2)).clamp(0, 1).pow(0.6)
      : float(1)

  // Running step: a second, fast pulse races around the ring.
  const racing = smoothstep(0.78, 1.0, fract(around.sub(now.mul(1.3)).add(offset))).pow(3.0).mul(live.active).mul(4.5)

  const level = float(spec.brightness)
    .mul(float(0.85).add(sweep).add(live.active.mul(1.4)).add(racing))
    .mul(float(1).sub(live.dim.mul(0.75)))
    // A failing ring strobes, so failure reads clearly even when the state is red.
    .mul(mix(float(1), step(0.45, fract(now.mul(9.0))).mul(1.6).add(0.15), live.fail.mul(0.9)))
    .mul(intensity)
    .mul(1.8)
  // The whole ring flares as a shockwave front passes through its radius.
  const wave = shockAt(cageScale.mul(spec.radius))
  // A failed step bleeds the ring to red, whatever the current state colour.
  const base = mix(stateColor(), RED, live.fail.mul(0.85))
  const flare = base.mul(0.6).add(WHITE_HOT.mul(0.25)).mul(wave.mul(2.2))
  const success = base.mul(0.45).add(WHITE_HOT.mul(0.6)).mul(live.flash.mul(3.0))
  material.colorNode = base.mul(level).add(flare).add(success).mul(depthFade())

  // Failure cracks the ring: segments drop out and flicker as it recovers.
  const cell = floor(around.mul(48.0)).add(floor(now.mul(14.0)).mul(7.0))
  const noise = fract(sin(cell.mul(12.9898)).mul(43758.5453))
  const intact = float(1).sub(step(noise, live.fail.mul(0.85)))
  material.opacityNode = segment.mul(edge).mul(intact)
  return material
}

function ringGeometry(spec: RingSpec) {
  if (spec.kind === 'line') return new THREE.TorusGeometry(spec.radius, spec.width, 6, 720)
  return new THREE.RingGeometry(spec.radius - spec.width / 2, spec.radius + spec.width / 2, 720, 1)
}

const SPIN_SPEEDS = RINGS.map((spec) => spec.spin)

const STEP_KICK: Partial<Record<RingStatus, number>> = { running: 0.35, done: 0.5, failed: 1.3 }

// When executing, every ring swings into nearly the same plane, slightly
// fanned, and spins together like a turbine.
const ALIGNED = RINGS.map((_, i) => new THREE.Quaternion().setFromEuler(new THREE.Euler(1.22 + i * 0.035, 0.18, i * 0.02)))
const OWN = RINGS.map((spec) => new THREE.Quaternion().setFromEuler(new THREE.Euler(...spec.tilt)))
const scratchQ = new THREE.Quaternion()
const wobbleQ = new THREE.Quaternion()
const wobbleE = new THREE.Euler()

export default function GyroRings() {
  const tilts = useRef<(THREE.Group | null)[]>([])
  const spinners = useRef<(THREE.Mesh | null)[]>([])
  const holder = useRef<THREE.Group | null>(null)

  const rings = useMemo(
    () =>
      RINGS.map((spec, index) => {
        const live = createRingLive()
        return { spec, live, geometry: ringGeometry(spec), material: ringMaterial(spec, index * 0.137, live) }
      }),
    [],
  )
  // Last step event seen per ring, to kick each ring once per change.
  const seen = useRef(RINGS.map(() => -Infinity))

  useEffect(() => () => {
    for (const ring of rings) {
      ring.geometry.dispose()
      ring.material.dispose()
    }
  }, [rings])

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05)
    const t = entityUniforms.clock.value as number
    spinRings(SPIN_SPEEDS, dt)
    const live = liveSignals.state
    const now = live.now
    // Real system strain makes every ring shiver slightly.
    const tremble = live.pressure * 0.012
    rings.forEach((ring, index) => {
      const step = live.rings[index]
      if (step && step.since !== seen.current[index]) {
        seen.current[index] = step.since
        const kick = STEP_KICK[step.status]
        if (kick) kickRing(index, kick)
      }
      const age = step ? now - step.since : Infinity
      const target = step?.status === 'running' ? 1 : 0
      ring.live.active.value += (target - (ring.live.active.value as number)) * (1 - Math.exp(-6 * dt))
      ring.live.flash.value = step?.status === 'done' ? Math.exp(-age * 1.8) : 0
      ring.live.fail.value = step?.status === 'failed' ? Math.exp(-age * 0.45) : 0
      ring.live.dim.value = step?.status === 'skipped' ? Math.exp(-age * 0.8) : 0

      const mesh = spinners.current[index]
      if (mesh) mesh.rotation.z = mood.ringAngle[index]
      const tilt = tilts.current[index]
      if (tilt) {
        // Own gyroscope tilt, blended toward the aligned "turbine" plane,
        // plus a spring wobble that rings after kicks and settles.
        scratchQ.copy(OWN[index]).slerp(ALIGNED[index], mood.align)
        const [wx, wy] = mood.ringWobble[index]
        const shiver = tremble * Math.sin(now * 23 + index * 1.7)
        wobbleQ.setFromEuler(wobbleE.set(wx + shiver, wy - shiver, 0))
        tilt.quaternion.copy(scratchQ).multiply(wobbleQ)
      }
    })
    if (holder.current) {
      // The whole gyroscope slowly turns, and breathes with the cage scale.
      holder.current.rotation.y = t * 0.035
      holder.current.rotation.x = Math.sin(t * 0.05) * 0.15
      holder.current.scale.setScalar(mood.cage)
    }
  })

  return (
    <group ref={holder}>
      {rings.map((ring, index) => (
        <group
          key={index}
          ref={(group) => {
            tilts.current[index] = group
          }}
        >
          <mesh
            ref={(mesh) => {
              spinners.current[index] = mesh
            }}
            geometry={ring.geometry}
            material={ring.material}
            frustumCulled={false}
          />
        </group>
      ))}
    </group>
  )
}
