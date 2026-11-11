import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { SpriteNodeMaterial } from 'three/webgpu'
import {
  abs, atan, cos, float, floor, fract, instancedBufferAttribute, int, mix, normalize, sin, smoothstep, step,
  uniform, uniformArray, uv, vec2, vec3,
} from 'three/tsl'
import type { Node } from 'three/webgpu'
import { entityUniforms, softDisc, stateColor, WHITE_HOT } from './entityUniforms'
import { liveSignals, type TrackedHand } from './liveSignals'
import { buildHandParticles, JOINTS, KIND, MAX_HANDS, pinchGlow, slotOf, toScene } from './handParticles'

/* =========================================================
   HOLO HANDS
   In gesture mode your hands appear in front of the entity,
   made of the same fine particles as the entity itself:
   energy streams along every bone from wrist to fingertip,
   the palm glows faintly and sparks circle the fingertips,
   all in the entity's state colour. A targeting reticle sits
   on your right index fingertip and locks tight as you pinch.

   Cost: the particle layout is built once; each frame only
   42 joint positions and two hand levels are sent to the GPU.
   With gesture mode off nothing is drawn.
   ========================================================= */

const FADE_IN = 10
const FADE_OUT = 4
const RETICLE_SIZE = 0.17

function hash(value: Node<'float'>) {
  return fract(sin(value.mul(12.9898)).mul(43758.5453))
}

export default function HoloHands() {
  const scene = useMemo(() => {
    const { now } = entityUniforms
    const layout = buildHandParticles()

    // Live inputs: 42 joint positions, and per hand (fade, engaged, pinch, 0).
    const jointValues = Array.from({ length: MAX_HANDS * JOINTS }, () => new THREE.Vector3(0, 0, 1.25))
    const handValues = Array.from({ length: MAX_HANDS }, () => new THREE.Vector4())
    const jointsU = uniformArray(jointValues, 'vec3')
    const handsU = uniformArray(handValues, 'vec4')

    const J = instancedBufferAttribute<'vec4'>(new THREE.InstancedBufferAttribute(layout.joints, 4), 'vec4')
    const W = instancedBufferAttribute<'vec4'>(new THREE.InstancedBufferAttribute(layout.weights, 4), 'vec4')
    const P = instancedBufferAttribute<'vec4'>(new THREE.InstancedBufferAttribute(layout.params, 4), 'vec4')
    // Element types are not inferred for uniform arrays; they are vec3 / vec4.
    const joint = (index: Node<'float'>) => jointsU.element(int(index)) as unknown as Node<'vec3'>
    const A = joint(J.x)
    const B = joint(J.y)
    const C = joint(J.z)
    const handIndex = floor(J.x.div(JOINTS))
    const hand = handsU.element(int(handIndex)) as unknown as Node<'vec4'>
    const fade = hand.x
    const engaged = hand.y
    const pinch = hand.z
    const seed = P.x
    const radius = P.y
    const speed = P.z
    const size = P.w

    const isTip = step(KIND.tip - 0.5, J.w)
    const isPalm = step(KIND.palm - 0.5, J.w).sub(isTip)
    const isBone = float(1).sub(isTip).sub(isPalm)

    // Bones: particles stream from the joint nearer the wrist towards the tip.
    const t = fract(W.y.add(now.mul(speed).mul(0.6)))
    const bone = mix(A, B, t)
    const palm = A.mul(W.x).add(B.mul(W.y)).add(C.mul(W.z))
    const base = bone.mul(isBone).add(palm.mul(isPalm)).add(A.mul(isTip))

    // A soft cloud around each bone, breathing slightly; sparks circle the tips.
    const cloud = normalize(vec3(hash(seed.mul(1.37)).sub(0.5), hash(seed.mul(2.71)).sub(0.5), hash(seed.mul(4.13)).sub(0.5)))
      .mul(radius)
      .mul(float(1).add(sin(now.mul(2.0).add(seed.mul(40.0))).mul(0.3)))
    const orbit = now.mul(speed).add(seed.mul(6.283))
    const spark = vec3(cos(orbit), sin(orbit), cos(orbit.mul(1.3))).mul(radius)
    const position = base.add(mix(cloud, spark, isTip))

    // Thumb and index tips flare as they pinch.
    const local = J.x.sub(handIndex.mul(JOINTS))
    const pinchTip = step(abs(local.sub(4)), float(0.5)).add(step(abs(local.sub(8)), float(0.5))).mul(isTip)

    const material = new SpriteNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    material.toneMapped = false
    material.positionNode = position
    material.scaleNode = vec2(mix(float(0.006), float(0.017), size).mul(fade))
    const energy = isBone.mul(float(0.7).add(t.mul(0.7))).add(isPalm.mul(0.45)).add(isTip.mul(1.25))
    const level = fade.mul(mix(float(0.4), float(1), engaged)).mul(float(1).add(pinchTip.mul(pinch).mul(2.0)))
    const hot = stateColor().mul(0.45).add(WHITE_HOT.mul(0.55))
    const color = mix(stateColor(), hot, isTip.mul(0.55).add(pinchTip.mul(pinch).mul(0.45)))
    material.colorNode = color.mul(energy).mul(level).mul(1.5)
    material.opacityNode = softDisc()
    const particles = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), material, layout.count)
    particles.frustumCulled = false

    // Targeting reticle on the right index fingertip.
    const lock = uniform(0)
    const reticleFade = uniform(0)
    const c = uv().sub(0.5)
    const d = c.length().mul(2.0)
    const angle = atan(c.y, c.x).add(now.mul(float(0.6).add(lock.mul(2.4))))
    const ring = smoothstep(0.05, 0.0, abs(d.sub(0.72)))
    const ticks = step(0.94, abs(cos(angle.mul(2.0)))).mul(smoothstep(0.09, 0.0, abs(d.sub(0.9))))
    const dot = smoothstep(0.1, 0.0, d).mul(lock.mul(0.8).add(0.2))
    const shape = ring.add(ticks.mul(0.9)).add(dot)
    const reticleMaterial = new SpriteNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    reticleMaterial.toneMapped = false
    reticleMaterial.colorNode = mix(stateColor(), WHITE_HOT, lock.mul(0.5).add(0.25)).mul(shape).mul(reticleFade).mul(1.8)
    reticleMaterial.opacityNode = shape.clamp(0, 1)
    const reticle = new THREE.Sprite(reticleMaterial)
    reticle.visible = false

    return { particles, reticle, jointValues, handValues, lock, reticleFade }
  }, [])

  useEffect(() => () => {
    scene.particles.geometry.dispose()
    ;(scene.particles.material as THREE.Material).dispose()
    ;(scene.reticle.material as THREE.Material).dispose()
  }, [scene])

  // Per slot: the last hand seen (kept while it fades out) and its fade level.
  const slots = useMemo(
    () => Array.from({ length: MAX_HANDS }, () => ({ hand: null as TrackedHand | null, fade: 0 })),
    [],
  )

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05)
    const seen = new Set<number>()
    for (const hand of liveSignals.state.hands) {
      const slot = slotOf(hand.side)
      seen.add(slot)
      slots[slot].hand = hand
    }
    let visible = false
    slots.forEach((entry, index) => {
      const target = seen.has(index) ? 1 : 0
      entry.fade += (target - entry.fade) * (1 - Math.exp(-(target ? FADE_IN : FADE_OUT) * dt))
      if (entry.fade < 0.01 && !target) {
        entry.fade = 0
        entry.hand = null
      }
      const hand = entry.hand
      if (hand) {
        hand.points.forEach((point, j) => scene.jointValues[index * JOINTS + j].set(...toScene(point)))
        visible = true
      }
      scene.handValues[index].set(entry.fade, hand?.engaged ? 1 : 0, hand ? pinchGlow(hand.pinch) : 0, 0)
    })
    scene.particles.visible = visible

    // Reticle: right hand only, while it is engaged.
    const right = slots[slotOf('Right')]
    const aim = right.hand && right.hand.engaged ? right.fade : 0
    const fade = scene.reticleFade.value as number
    scene.reticleFade.value = fade + (aim - fade) * (1 - Math.exp(-12 * dt))
    if (right.hand) {
      const lock = pinchGlow(right.hand.pinch)
      scene.lock.value = lock
      const [x, y, z] = toScene(right.hand.points[8])
      scene.reticle.position.set(x, y, z + 0.02)
      scene.reticle.scale.setScalar(RETICLE_SIZE * (1 - lock * 0.35))
    }
    scene.reticle.visible = (scene.reticleFade.value as number) > 0.01
  })

  return (
    <group>
      <primitive object={scene.particles} />
      <primitive object={scene.reticle} />
    </group>
  )
}
