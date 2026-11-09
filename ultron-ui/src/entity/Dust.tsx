import { useEffect, useMemo } from 'react'
import * as THREE from 'three/webgpu'
import { SpriteNodeMaterial } from 'three/webgpu'
import { cos, float, fract, sin, vec2 } from 'three/tsl'
import { buildOrbits, depthFade, entityUniforms, shockAt, softDisc, stateColor } from './entityUniforms'

/* =========================================================
   DUST
   A sparse halo of faint sparks drifting on slow, wide,
   independent orbits around the whole entity. Gives depth
   without forming a cloud.
   ========================================================= */

const DUST_COUNT = 1800

export default function Dust() {
  const mesh = useMemo(() => {
    const { clock, intensity } = entityUniforms
    const orbit = buildOrbits(
      DUST_COUNT,
      (x) => 1.55 + x * 1.4,
      (_r, s) => (0.04 + s * 0.08) * (s < 0.5 ? -1 : 1),
    )
    const radius = orbit.p.x
    const seed = orbit.p.w
    const theta = orbit.p.y.add(clock.mul(orbit.p.z))
    const material = new SpriteNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    material.toneMapped = false
    const wave = shockAt(radius)
    material.positionNode = orbit.u.mul(cos(theta)).add(orbit.w.mul(sin(theta))).mul(radius.add(wave.mul(0.25)))
    material.scaleNode = vec2(float(0.006).add(fract(seed.mul(13.7)).mul(0.01)))
    const flicker = float(0.4).add(sin(clock.mul(2.3).add(seed.mul(70.0))).mul(0.6)).clamp(0, 1)
    const fade = float(1).sub(radius.sub(1.55).div(1.4)).clamp(0.15, 1)
    material.colorNode = stateColor().mul(flicker.mul(fade).mul(intensity).mul(0.9).add(wave.mul(1.2))).mul(depthFade())
    material.opacityNode = softDisc()
    const instanced = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), material, DUST_COUNT)
    instanced.frustumCulled = false
    return instanced
  }, [])

  useEffect(() => () => {
    mesh.geometry.dispose()
    ;(mesh.material as THREE.Material).dispose()
  }, [mesh])

  return <primitive object={mesh} />
}
