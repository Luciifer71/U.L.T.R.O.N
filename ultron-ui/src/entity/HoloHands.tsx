import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { LineBasicNodeMaterial, SpriteNodeMaterial } from 'three/webgpu'
import { attribute, float, instancedBufferAttribute, sin } from 'three/tsl'
import { BLUE, entityUniforms, softDisc, WHITE_HOT } from './entityUniforms'
import { liveSignals, type TrackedHand } from './liveSignals'
import { createHandBuffers, JOINTS, MAX_HANDS, slotOf, writeHand } from './holoHands'

/* =========================================================
   HOLO HANDS
   In gesture mode your tracked hands appear in front of the
   entity as glowing holographic skeletons: thin bones and
   bright joints, fingertips hottest, thumb and index flaring
   as they pinch. 42 points a frame are written from the CPU;
   with gesture mode off nothing is drawn or uploaded.
   ========================================================= */

const FADE_IN = 10
const FADE_OUT = 4

export default function HoloHands() {
  const { lines, joints, buffers, attributes } = useMemo(() => {
    const buffers = createHandBuffers()
    const { now } = entityUniforms
    // Cool hologram blue with a white core; a faint scan shimmer runs up the hand.
    const holo = BLUE.mul(0.9).add(WHITE_HOT.mul(0.25))

    const lineGeometry = new THREE.BufferGeometry()
    // BufferAttribute shares the arrays (Float32BufferAttribute would copy them).
    const linePosition = new THREE.BufferAttribute(buffers.linePositions, 3)
    const lineGlow = new THREE.BufferAttribute(buffers.lineGlow, 1)
    linePosition.setUsage(THREE.DynamicDrawUsage)
    lineGlow.setUsage(THREE.DynamicDrawUsage)
    lineGeometry.setAttribute('position', linePosition)
    lineGeometry.setAttribute('glow', lineGlow)
    const lineMaterial = new LineBasicNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    lineMaterial.toneMapped = false
    const glow = attribute('glow', 'float')
    const y = attribute('position', 'vec3').y
    const shimmer = float(0.8).add(sin(y.mul(18.0).sub(now.mul(4.0))).mul(0.2))
    lineMaterial.colorNode = holo.mul(glow).mul(shimmer).mul(1.6)
    const lines = new THREE.LineSegments(lineGeometry, lineMaterial)
    lines.frustumCulled = false

    const count = MAX_HANDS * JOINTS
    const jointPosition = new THREE.InstancedBufferAttribute(buffers.jointPositions, 3)
    const jointGlow = new THREE.InstancedBufferAttribute(buffers.jointGlow, 2)
    jointPosition.setUsage(THREE.DynamicDrawUsage)
    jointGlow.setUsage(THREE.DynamicDrawUsage)
    const centre = instancedBufferAttribute<'vec3'>(jointPosition, 'vec3')
    const look = instancedBufferAttribute<'vec2'>(jointGlow, 'vec2')
    const jointMaterial = new SpriteNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    jointMaterial.toneMapped = false
    jointMaterial.positionNode = centre
    jointMaterial.scaleNode = look.y
    jointMaterial.colorNode = holo.mul(0.7).add(WHITE_HOT.mul(0.45)).mul(look.x).mul(2.2)
    jointMaterial.opacityNode = softDisc()
    const joints = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), jointMaterial, count)
    joints.frustumCulled = false

    return {
      lines,
      joints,
      buffers,
      attributes: [linePosition, lineGlow, jointPosition, jointGlow],
    }
  }, [])

  useEffect(() => () => {
    lines.geometry.dispose()
    ;(lines.material as THREE.Material).dispose()
    joints.geometry.dispose()
    ;(joints.material as THREE.Material).dispose()
  }, [lines, joints])

  // Per slot: the last hand seen (kept while it fades out) and its fade level.
  const slots = useMemo(() => Array.from({ length: MAX_HANDS }, () => ({ hand: null as TrackedHand | null, fade: 0 })), [])

  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05)
    const seen = new Set<number>()
    for (const hand of liveSignals.state.hands) {
      const slot = slotOf(hand.side)
      seen.add(slot)
      slots[slot].hand = hand
    }
    let visible = false
    let changed = false
    slots.forEach((entry, index) => {
      const target = seen.has(index) ? 1 : 0
      const before = entry.fade
      entry.fade += (target - entry.fade) * (1 - Math.exp(-(target ? FADE_IN : FADE_OUT) * dt))
      if (entry.fade < 0.01 && !target) {
        entry.fade = 0
        entry.hand = null
      }
      if (entry.hand || before !== entry.fade) {
        writeHand(buffers, index, entry.hand, entry.fade)
        changed = true
      }
      if (entry.fade > 0) visible = true
    })
    lines.visible = visible
    joints.visible = visible
    if (changed) for (const attr of attributes) attr.needsUpdate = true
  })

  return (
    <group>
      <primitive object={lines} />
      <primitive object={joints} />
    </group>
  )
}
