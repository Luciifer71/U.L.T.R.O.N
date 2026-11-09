import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { MeshBasicNodeMaterial } from 'three/webgpu'
import { atan, float, fract, positionLocal, smoothstep, step } from 'three/tsl'
import { depthFade, entityUniforms, shockAt, stateColor, WHITE_HOT } from './entityUniforms'
import { mood, spinRings } from './mood'
import { RINGS, type RingSpec } from './entityConfig'

/* =========================================================
   GYROSCOPE RINGS
   Thin luminous rings around the core, each made of
   segmented arcs, dashes or tick marks, each spinning on
   its own tilted axis. A bright highlight sweeps around
   every ring. All patterns are drawn in the fragment shader
   from the angle around the ring, so a ring costs one draw.
   ========================================================= */

function ringMaterial(spec: RingSpec, offset: number) {
  const { clock, intensity, cageScale } = entityUniforms
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

  const level = float(spec.brightness).mul(float(0.85).add(sweep)).mul(intensity).mul(1.8)
  // The whole ring flares as a shockwave front passes through its radius.
  const wave = shockAt(cageScale.mul(spec.radius))
  const base = stateColor()
  material.colorNode = base.mul(level).add(base.mul(0.6).add(WHITE_HOT.mul(0.25)).mul(wave.mul(2.2))).mul(depthFade())
  material.opacityNode = segment.mul(edge)
  return material
}

function ringGeometry(spec: RingSpec) {
  if (spec.kind === 'line') return new THREE.TorusGeometry(spec.radius, spec.width, 6, 720)
  return new THREE.RingGeometry(spec.radius - spec.width / 2, spec.radius + spec.width / 2, 720, 1)
}

const SPIN_SPEEDS = RINGS.map((spec) => spec.spin)

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
      RINGS.map((spec, index) => ({
        spec,
        geometry: ringGeometry(spec),
        material: ringMaterial(spec, index * 0.137),
      })),
    [],
  )

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
    rings.forEach((_ring, index) => {
      const mesh = spinners.current[index]
      if (mesh) mesh.rotation.z = mood.ringAngle[index]
      const tilt = tilts.current[index]
      if (tilt) {
        // Own gyroscope tilt, blended toward the aligned "turbine" plane,
        // plus a spring wobble that rings after kicks and settles.
        scratchQ.copy(OWN[index]).slerp(ALIGNED[index], mood.align)
        const [wx, wy] = mood.ringWobble[index]
        wobbleQ.setFromEuler(wobbleE.set(wx, wy, 0))
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
