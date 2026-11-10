import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { SpriteNodeMaterial } from 'three/webgpu'
import { cos, cross, float, instancedBufferAttribute, mix, select, sin, smoothstep, step, vec2, vec3 } from 'three/tsl'
import { BLUE, depthFade, entityUniforms, softDisc, stateColor, WHITE_HOT } from './entityUniforms'
import { liveSignals, PACKET_SLOTS } from './liveSignals'

/* =========================================================
   DATA STREAM
   Words as data: each word you say streams into the core as
   a glowing packet on a curved path; each word of ULTRON's
   reply streams back out. A packet is a short comet (head +
   fading trail). Packets are written to the GPU only when a
   message arrives; their motion is computed in the shader
   from the time they were spawned.
   ========================================================= */

const TRAIL = 14
const INSTANCES = PACKET_SLOTS * TRAIL
const DURATION = 1.7 // seconds from the edge of the scene to the core
const OUTER = 3.1
const INNER = 0.05
const NEVER = -1e4 // spawn time of an unused slot (finite, see mood.ts NO_EVENT)

export default function DataStream() {
  const { mesh, directions, params } = useMemo(() => {
    const { now, intensity } = entityUniforms

    const directionArray = new Float32Array(INSTANCES * 3)
    // spawn time, inbound (1) / outbound (0), trail index, seed
    const paramArray = new Float32Array(INSTANCES * 4)
    for (let i = 0; i < INSTANCES; i++) {
      directionArray.set([0, 1, 0], i * 3)
      paramArray.set([NEVER, 0, i % TRAIL, 0], i * 4)
    }
    const directions = new THREE.InstancedBufferAttribute(directionArray, 3)
    const params = new THREE.InstancedBufferAttribute(paramArray, 4)
    directions.setUsage(THREE.DynamicDrawUsage)
    params.setUsage(THREE.DynamicDrawUsage)
    const direction = instancedBufferAttribute<'vec3'>(directions, 'vec3')
    const param = instancedBufferAttribute<'vec4'>(params, 'vec4')

    const inbound = param.y.greaterThan(0.5)
    const trail = param.z
    const seed = param.w
    const progress = now.sub(param.x).div(DURATION).sub(trail.mul(0.011))
    const visible = step(0.0, progress).mul(step(progress, 1.0))
    const p = progress.clamp(0, 1)
    const eased = p.mul(p).mul(float(3).sub(p.mul(2)))
    const radius = select(inbound, mix(float(OUTER), float(INNER), eased), mix(float(INNER), float(OUTER), eased))

    // Curve the path: swing around a perpendicular axis as the packet travels.
    const side = cross(direction, vec3(0.31, 0.95, 0.07)).normalize()
    const swing = select(inbound, float(1).sub(eased), eased).mul(seed.mul(2.0).sub(1.0)).mul(1.4)
    const position = direction.mul(cos(swing)).add(side.mul(sin(swing))).mul(radius)

    const material = new SpriteNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    material.toneMapped = false
    material.positionNode = position
    const tail = float(1).sub(trail.div(TRAIL))
    material.scaleNode = vec2(float(0.01).add(tail.mul(0.024)).mul(visible))

    // Words in read as incoming information (blue); replies carry ULTRON's colour.
    const base = stateColor()
    const color = select(inbound, mix(base, BLUE, 0.7).add(WHITE_HOT.mul(0.15)), base.add(WHITE_HOT.mul(0.25)))
    const fade = smoothstep(0.0, 0.08, p).mul(smoothstep(1.0, 0.8, p)).mul(tail.pow(1.5))
    material.colorNode = color.mul(fade).mul(visible).mul(float(0.8).add(intensity)).mul(2.2).mul(depthFade())
    material.opacityNode = softDisc()

    const instanced = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), material, INSTANCES)
    instanced.frustumCulled = false
    return { mesh: instanced, directions, params }
  }, [])

  useEffect(() => () => {
    mesh.geometry.dispose()
    ;(mesh.material as THREE.Material).dispose()
  }, [mesh])

  useFrame(() => {
    const packets = liveSignals.takeNewPackets()
    if (packets.length === 0) return
    const directionArray = directions.array as Float32Array
    const paramArray = params.array as Float32Array
    for (const packet of packets) {
      for (let t = 0; t < TRAIL; t++) {
        const i = packet.slot * TRAIL + t
        directionArray.set(packet.direction, i * 3)
        paramArray.set([packet.spawn, packet.inbound ? 1 : 0, t, packet.seed], i * 4)
      }
    }
    directions.needsUpdate = true
    params.needsUpdate = true
  })

  return <primitive object={mesh} />
}
