import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { SpriteNodeMaterial } from 'three/webgpu'
import { cos, cross, float, fract, mix, mx_noise_vec3, sin, smoothstep, uv, vec2, vec3 } from 'three/tsl'
import { mood } from './mood'
import { buildOrbits, entityUniforms, shockAt, softDisc, stateColor, WHITE_HOT } from './entityUniforms'

/* =========================================================
   PARTICLE CORE
   A dense nucleus of independent particles. Each particle
   has its own orbit plane, radius, speed and phase, chosen
   once at startup. Its position each frame is a pure
   function of the shared entity clock, computed in the
   vertex shader: no particle reads any other, and there is
   no per-frame compute pass.
   ========================================================= */

const CORE_COUNT = 26000
const CORE_RADIUS = 0.62

export default function ParticleCore() {
  const { mesh, corona } = useMemo(() => {
    const { clock, intensity, coreGlow, turbulence, coreScale, flow } = entityUniforms

    // Denser towards the centre; inner particles orbit faster.
    const orbit = buildOrbits(
      CORE_COUNT,
      (x) => 0.05 + CORE_RADIUS * Math.pow(x, 1.7),
      (r, s) => (0.35 + s * 0.55) / (0.28 + r) * (s < 0.18 ? -1 : 1),
    )
    const radius = orbit.p.x
    const seed = orbit.p.w

    const theta = orbit.p.y.add(clock.mul(orbit.p.z))
    const normal = cross(orbit.u, orbit.w)
    const breath = float(1).add(sin(clock.mul(0.8).add(seed.mul(6.283))).mul(0.05))
    // Small out-of-plane wobble, stronger when the entity is agitated.
    const wobble = normal.mul(sin(theta.mul(3.0).add(seed.mul(40.0))).mul(radius).mul(float(0.04).add(turbulence.mul(0.06))))
    const orbitPosition = orbit.u.mul(cos(theta)).add(orbit.w.mul(sin(theta))).mul(radius.mul(breath)).add(wobble).mul(coreScale)

    // Fluid motion: a slowly drifting 3D noise field bends every orbit, like
    // smoke caught in a current. Pure function of position and clock.
    const current = mx_noise_vec3(orbitPosition.mul(2.2).add(vec3(0, clock.mul(0.12), clock.mul(0.07))))
    const fluid = current.mul(flow).mul(float(0.035).add(radius.mul(0.11)))

    // Shockwaves push particles outward and light them up as they pass.
    const distance = orbitPosition.length()
    const wave = shockAt(distance)
    const position = orbitPosition.add(fluid).add(orbitPosition.normalize().mul(wave.mul(0.14)))

    const material = new SpriteNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    material.toneMapped = false
    material.positionNode = position
    material.scaleNode = vec2(mix(float(0.006), float(0.02), fract(seed.mul(7.31))))

    // White-hot centre fading to the state colour at the edge.
    const coreness = float(1).sub(smoothstep(0.04, CORE_RADIUS + 0.05, radius))
    const base = stateColor()
    const hot = base.mul(0.35).add(WHITE_HOT.mul(0.65))
    const color = mix(base, hot, coreness.pow(4.0).mul(0.55))
    const twinkle = float(0.75).add(sin(clock.mul(3.0).add(seed.mul(50.0))).mul(0.25))
    const energy = float(0.3).add(coreness.pow(1.5).mul(0.85)).mul(intensity).mul(float(0.55).add(coreGlow.mul(0.6))).mul(twinkle)
    material.colorNode = color.mul(energy).add(base.mul(0.5).add(WHITE_HOT.mul(0.3)).mul(wave.mul(1.6)))
    material.opacityNode = softDisc()

    const instanced = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), material, CORE_COUNT)
    instanced.frustumCulled = false

    // A soft corona behind the nucleus so the core reads as one glowing body.
    const coronaMaterial = new SpriteNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    coronaMaterial.toneMapped = false
    const d = uv().sub(0.5).length().mul(2.0)
    const falloff = float(1).sub(d).clamp(0, 1).pow(3.0)
    coronaMaterial.colorNode = base.mul(0.5).add(WHITE_HOT.mul(0.04)).mul(coreGlow).mul(0.32)
    coronaMaterial.opacityNode = falloff
    const coronaSprite = new THREE.Sprite(coronaMaterial)
    coronaSprite.scale.setScalar(1.9)

    return { mesh: instanced, corona: coronaSprite }
  }, [])

  useEffect(() => () => {
    mesh.geometry.dispose()
    ;(mesh.material as THREE.Material).dispose()
    ;(corona.material as THREE.Material).dispose()
  }, [mesh, corona])

  useFrame(() => {
    corona.scale.setScalar(1.9 * mood.core)
  })

  return (
    <group>
      <primitive object={corona} />
      <primitive object={mesh} />
    </group>
  )
}
