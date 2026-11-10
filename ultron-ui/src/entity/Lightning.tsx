import { useEffect, useMemo } from 'react'
import * as THREE from 'three/webgpu'
import { LineBasicNodeMaterial } from 'three/webgpu'
import { attribute, cos, cross, float, floor, fract, normalize, sin, sqrt, step, vec3 } from 'three/tsl'
import type { Node } from 'three/webgpu'
import { BLUE, depthFade, entityUniforms, stateColor, WHITE_HOT } from './entityUniforms'

/* =========================================================
   LIGHTNING
   Jagged electric arcs from the core out to the ring cage,
   visible while ULTRON thinks or the model is working. Each
   bolt re-strikes several times a second along a new random
   path. Everything is computed in the vertex shader from the
   bolt's seed and the current "strike" number, so the layer
   is a single static line geometry with no CPU work per frame.
   ========================================================= */

const BOLTS = 7
const SEGMENTS = 14

function hash(value: Node<'float'>) {
  return fract(sin(value.mul(12.9898)).mul(43758.5453))
}

function buildBolts() {
  const vertices = BOLTS * SEGMENTS * 2
  const params = new Float32Array(vertices * 2) // bolt seed, step along the bolt (0..SEGMENTS)
  let v = 0
  for (let bolt = 0; bolt < BOLTS; bolt++) {
    const seed = bolt * 17.31 + 3.7
    for (let s = 0; s < SEGMENTS; s++) {
      for (const k of [s, s + 1]) {
        params.set([seed, k], v * 2)
        v++
      }
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(vertices * 3), 3))
  geometry.setAttribute('bolt', new THREE.Float32BufferAttribute(params, 2))
  return geometry
}

export default function Lightning() {
  const lines = useMemo(() => {
    const { now, lightning, intensity } = entityUniforms
    const bolt = attribute('bolt', 'vec2')
    const seed = bolt.x
    const t = bolt.y.div(SEGMENTS)

    // Each bolt re-strikes at its own rhythm (about 5-11 times a second).
    const rate = float(5).add(hash(seed.add(1.1)).mul(6))
    const strike = floor(now.mul(rate).add(hash(seed).mul(10)))
    const strikeSeed = seed.add(strike.mul(7.13))

    // Random direction for this strike (uniform on the sphere).
    const z = hash(strikeSeed.add(0.3)).mul(2).sub(1)
    const angle = hash(strikeSeed.add(0.7)).mul(Math.PI * 2)
    const ring = sqrt(float(1).sub(z.mul(z)))
    const direction = vec3(cos(angle).mul(ring), z, sin(angle).mul(ring))
    const side = normalize(cross(direction, vec3(0.19, 0.97, 0.13)))
    const up = cross(direction, side)

    // From the core surface out to the ring cage, jagged in between.
    const reach = float(0.85).add(hash(strikeSeed.add(2.9)).mul(0.6))
    const along = direction.mul(float(0.12).add(t.mul(reach.sub(0.12))))
    const envelope = t.mul(float(1).sub(t)).mul(4) // 0 at both ends, 1 in the middle
    const k = bolt.y
    const jitterA = hash(strikeSeed.add(k.mul(3.17))).sub(0.5)
    const jitterB = hash(strikeSeed.add(k.mul(5.71)).add(9.1)).sub(0.5)
    const jag = side.mul(jitterA).add(up.mul(jitterB)).mul(envelope).mul(0.16)

    const material = new LineBasicNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    material.toneMapped = false
    material.positionNode = along.add(jag)

    // Only some bolts fire on each strike; more as the lightning level rises.
    const fires = step(hash(strikeSeed.add(4.4)), lightning.mul(0.85))
    const flicker = float(0.55).add(hash(strikeSeed.add(6.6)).mul(0.9))
    const color = stateColor().mul(0.45).add(BLUE.mul(0.25)).add(WHITE_HOT.mul(0.55))
    material.colorNode = color.mul(fires).mul(flicker).mul(lightning).mul(float(0.8).add(intensity)).mul(2.6).mul(depthFade())

    const object = new THREE.LineSegments(buildBolts(), material)
    object.frustumCulled = false
    return object
  }, [])

  useEffect(() => () => {
    lines.geometry.dispose()
    ;(lines.material as THREE.Material).dispose()
  }, [lines])

  return <primitive object={lines} />
}
