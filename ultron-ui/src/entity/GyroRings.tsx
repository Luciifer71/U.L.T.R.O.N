import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { MeshBasicNodeMaterial } from 'three/webgpu'
import { atan, float, fract, positionLocal, smoothstep, step } from 'three/tsl'
import { entityUniforms, stateColor } from './entityUniforms'

/* =========================================================
   GYROSCOPE RINGS
   Thin luminous rings around the core, each made of
   segmented arcs, dashes or tick marks, each spinning on
   its own tilted axis. A bright highlight sweeps around
   every ring. All patterns are drawn in the fragment shader
   from the angle around the ring, so a ring costs one draw.
   ========================================================= */

type RingKind = 'line' | 'band'

type RingSpec = {
  kind: RingKind
  radius: number
  width: number // tube radius for lines, band width for bands
  count: number // segments around the ring (0 = continuous)
  duty: number // lit fraction of each segment
  spin: number // radians per entity-clock second
  tilt: [number, number, number]
  brightness: number
  sweep: number // highlight sweep speed (turns per clock second)
}

const RINGS: RingSpec[] = [
  { kind: 'line', radius: 0.8, width: 0.0028, count: 0, duty: 1, spin: 0.35, tilt: [1.2, 0.2, 0], brightness: 1.0, sweep: 0.22 },
  { kind: 'band', radius: 0.9, width: 0.035, count: 120, duty: 0.2, spin: -0.22, tilt: [0.35, 1.1, 0.2], brightness: 0.55, sweep: 0.15 },
  { kind: 'line', radius: 1.0, width: 0.0024, count: 36, duty: 0.72, spin: 0.18, tilt: [-0.6, 0.4, 0.9], brightness: 0.9, sweep: -0.18 },
  { kind: 'band', radius: 1.08, width: 0.022, count: 6, duty: 0.62, spin: -0.12, tilt: [1.55, 0.0, 0.5], brightness: 0.75, sweep: 0.12 },
  { kind: 'line', radius: 1.18, width: 0.002, count: 90, duty: 0.45, spin: 0.1, tilt: [0.15, -0.9, -0.3], brightness: 0.7, sweep: 0.1 },
  { kind: 'band', radius: 1.27, width: 0.06, count: 240, duty: 0.1, spin: -0.07, tilt: [0.9, 0.7, -0.6], brightness: 0.45, sweep: -0.08 },
  { kind: 'line', radius: 1.38, width: 0.0022, count: 3, duty: 0.82, spin: 0.08, tilt: [-1.1, -0.3, 0.2], brightness: 0.8, sweep: 0.07 },
  { kind: 'line', radius: 1.5, width: 0.0016, count: 0, duty: 1, spin: -0.05, tilt: [0.5, 1.4, 0.9], brightness: 0.35, sweep: -0.05 },
]

function ringMaterial(spec: RingSpec, offset: number) {
  const { clock, intensity } = entityUniforms
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
  material.colorNode = stateColor().mul(level)
  material.opacityNode = segment.mul(edge)
  return material
}

function ringGeometry(spec: RingSpec) {
  if (spec.kind === 'line') return new THREE.TorusGeometry(spec.radius, spec.width, 6, 720)
  return new THREE.RingGeometry(spec.radius - spec.width / 2, spec.radius + spec.width / 2, 720, 1)
}

export default function GyroRings() {
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

  useFrame(() => {
    const t = entityUniforms.clock.value as number
    rings.forEach((ring, index) => {
      const mesh = spinners.current[index]
      if (mesh) mesh.rotation.z = t * ring.spec.spin
    })
    // The whole gyroscope slowly turns so the rings never look static.
    if (holder.current) {
      holder.current.rotation.y = t * 0.035
      holder.current.rotation.x = Math.sin(t * 0.05) * 0.15
    }
  })

  return (
    <group ref={holder}>
      {rings.map((ring, index) => (
        <group key={index} rotation={ring.spec.tilt}>
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
