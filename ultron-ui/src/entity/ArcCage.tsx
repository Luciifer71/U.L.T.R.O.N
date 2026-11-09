import { useEffect, useMemo } from 'react'
import * as THREE from 'three/webgpu'
import { LineBasicNodeMaterial } from 'three/webgpu'
import { attribute, cos, float, fract, sin, smoothstep } from 'three/tsl'
import { entityUniforms, stateColor, WHITE_HOT } from './entityUniforms'

/* =========================================================
   ARC CAGE
   Many short luminous arcs on spheres around the core, each
   on its own great circle and spinning at its own speed:
   the dense "gyroscopic cage" look from the reference
   frames. Every vertex carries its arc's orbit basis, so the
   whole cage is one draw and each arc moves independently.
   ========================================================= */

const ARC_COUNT = 90
const ARC_SEGMENTS = 56

function buildArcs() {
  const vertices = ARC_COUNT * ARC_SEGMENTS * 2
  const u = new Float32Array(vertices * 3)
  const w = new Float32Array(vertices * 3)
  // angle along the arc, radius, spin speed, 0..1 position along the arc
  const params = new Float32Array(vertices * 4)
  const seeds = new Float32Array(vertices)
  const axis = new THREE.Vector3()
  const a = new THREE.Vector3()
  const b = new THREE.Vector3()
  const helper = new THREE.Vector3()
  let v = 0
  for (let arc = 0; arc < ARC_COUNT; arc++) {
    axis.randomDirection()
    helper.set(Math.abs(axis.x) < 0.9 ? 1 : 0, Math.abs(axis.x) < 0.9 ? 0 : 1, 0)
    a.crossVectors(axis, helper).normalize()
    b.crossVectors(axis, a).normalize()
    const radius = 0.86 + Math.pow(Math.random(), 0.8) * 0.62
    const length = (0.25 + Math.random() * 1.6) // radians
    const start = Math.random() * Math.PI * 2
    const speed = (0.08 + Math.random() * 0.3) * (Math.random() < 0.5 ? -1 : 1)
    const seed = Math.random()
    for (let s = 0; s < ARC_SEGMENTS; s++) {
      for (const k of [s, s + 1]) {
        const f = k / ARC_SEGMENTS
        u.set([a.x, a.y, a.z], v * 3)
        w.set([b.x, b.y, b.z], v * 3)
        params.set([start + f * length, radius, speed, f], v * 4)
        seeds[v] = seed
        v++
      }
    }
  }
  const geometry = new THREE.BufferGeometry()
  // A position attribute is required; real positions come from positionNode.
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(vertices * 3), 3))
  geometry.setAttribute('arcU', new THREE.Float32BufferAttribute(u, 3))
  geometry.setAttribute('arcW', new THREE.Float32BufferAttribute(w, 3))
  geometry.setAttribute('arcP', new THREE.Float32BufferAttribute(params, 4))
  geometry.setAttribute('arcSeed', new THREE.Float32BufferAttribute(seeds, 1))
  return geometry
}

export default function ArcCage() {
  const lines = useMemo(() => {
    const { clock, intensity, motion } = entityUniforms
    const arcU = attribute('arcU', 'vec3')
    const arcW = attribute('arcW', 'vec3')
    const arcP = attribute('arcP', 'vec4')
    const seed = attribute('arcSeed', 'float')

    const angle = arcP.x.add(clock.mul(arcP.z))
    const material = new LineBasicNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    material.toneMapped = false
    material.positionNode = arcU.mul(cos(angle)).add(arcW.mul(sin(angle))).mul(arcP.y)

    // Arcs fade in at both ends; a bright pulse runs along each one.
    const along = arcP.w
    const ends = smoothstep(0.0, 0.18, along).mul(smoothstep(1.0, 0.82, along))
    const run = fract(clock.mul(float(0.25).add(motion.mul(0.5))).add(seed))
    const pulse = smoothstep(0.1, 0.0, along.sub(run).abs()).mul(1.6)
    const flicker = float(0.7).add(sin(clock.mul(2.0).add(seed.mul(60.0))).mul(0.3))
    const base = stateColor()
    const color = base.mul(float(0.55).mul(flicker)).add(base.mul(0.5).add(WHITE_HOT.mul(0.4)).mul(pulse))
    material.colorNode = color.mul(ends).mul(intensity).mul(1.5)
    const object = new THREE.LineSegments(buildArcs(), material)
    object.frustumCulled = false
    return object
  }, [])

  useEffect(() => () => {
    lines.geometry.dispose()
    ;(lines.material as THREE.Material).dispose()
  }, [lines])

  return <primitive object={lines} />
}
