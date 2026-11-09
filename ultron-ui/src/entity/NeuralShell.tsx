import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { LineBasicNodeMaterial, SpriteNodeMaterial } from 'three/webgpu'
import { attribute, float, fract, instancedBufferAttribute, mix, select, sin, smoothstep, vec2 } from 'three/tsl'
import { BLUE, entityUniforms, softDisc, stateColor, WHITE_HOT } from './entityUniforms'

/* =========================================================
   NEURAL SHELL
   Nodes spread over a sphere around the rings, each joined
   to its nearest neighbours by a thin line. Pulses of light
   travel along the lines; more of them, and brighter, when
   ULTRON is taking in or processing information.
   Geometry is built once; pulses are computed per pixel
   from the entity clock.
   ========================================================= */

const NODE_COUNT = 280
const SHELL_RADIUS = 1.78
const LINKS_PER_NODE = 3
const MAX_LINK = 0.62

function buildNetwork() {
  const nodes: THREE.Vector3[] = []
  const golden = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < NODE_COUNT; i++) {
    const y = 1 - (i / (NODE_COUNT - 1)) * 2
    const ring = Math.sqrt(1 - y * y)
    const angle = golden * i
    const jitter = SHELL_RADIUS * (0.95 + Math.random() * 0.08)
    nodes.push(new THREE.Vector3(Math.cos(angle) * ring, y, Math.sin(angle) * ring).multiplyScalar(jitter))
  }

  const seen = new Set<string>()
  const positions: number[] = []
  const along: number[] = []
  const pulse: number[] = []
  nodes.forEach((node, i) => {
    const nearest = nodes
      .map((other, j) => ({ j, d: node.distanceTo(other) }))
      .filter(({ j, d }) => j !== i && d < MAX_LINK)
      .sort((a, b) => a.d - b.d)
      .slice(0, LINKS_PER_NODE)
    for (const { j } of nearest) {
      const key = i < j ? `${i}-${j}` : `${j}-${i}`
      if (seen.has(key)) continue
      seen.add(key)
      const other = nodes[j]
      positions.push(node.x, node.y, node.z, other.x, other.y, other.z)
      along.push(0, 1)
      // phase, speed (signed = direction)
      const phase = Math.random()
      const speed = (0.12 + Math.random() * 0.3) * (Math.random() < 0.5 ? -1 : 1)
      pulse.push(phase, speed, phase, speed)
    }
  })

  const lines = new THREE.BufferGeometry()
  lines.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  lines.setAttribute('along', new THREE.Float32BufferAttribute(along, 1))
  lines.setAttribute('pulse', new THREE.Float32BufferAttribute(pulse, 2))

  const nodeData = new Float32Array(NODE_COUNT * 4)
  nodes.forEach((node, i) => nodeData.set([node.x, node.y, node.z, Math.random()], i * 4))
  return { lines, nodeData }
}

export default function NeuralShell() {
  const holder = useRef<THREE.Group | null>(null)

  const { lineObject, nodeMesh } = useMemo(() => {
    const { clock, intensity, information } = entityUniforms
    const { lines, nodeData } = buildNetwork()

    // ---- lines with travelling pulses
    const lineMaterial = new LineBasicNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    lineMaterial.toneMapped = false
    const along = attribute('along', 'float')
    const pulse = attribute('pulse', 'vec2')
    const travel = fract(clock.mul(pulse.y.abs()).add(pulse.x))
    const position = select(pulse.y.greaterThan(0), along, float(1).sub(along))
    const head = smoothstep(0.12, 0.0, position.sub(travel).abs())
    const pulseGain = float(0.5).add(information.mul(1.4))
    const base = stateColor()
    // Information pulses lean blue, like data moving through the network.
    const pulseColor = mix(base, BLUE, information.mul(0.5)).mul(0.75).add(WHITE_HOT.mul(0.08))
    lineMaterial.colorNode = base.mul(0.05).add(pulseColor.mul(head).mul(pulseGain)).mul(intensity).mul(1.2)
    const lineObject = new THREE.LineSegments(lines, lineMaterial)
    lineObject.frustumCulled = false

    // ---- glowing nodes
    const node = instancedBufferAttribute<'vec4'>(new THREE.InstancedBufferAttribute(nodeData, 4), 'vec4')
    const nodeMaterial = new SpriteNodeMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending })
    nodeMaterial.toneMapped = false
    nodeMaterial.positionNode = node.xyz
    const twinkle = float(0.55).add(sin(clock.mul(1.7).add(node.w.mul(40.0))).mul(0.45))
    nodeMaterial.scaleNode = vec2(float(0.016).add(node.w.mul(0.018)))
    nodeMaterial.colorNode = base.mul(0.7).add(WHITE_HOT.mul(0.15)).mul(twinkle).mul(intensity).mul(1.1)
    nodeMaterial.opacityNode = softDisc()
    const nodeMesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), nodeMaterial, NODE_COUNT)
    nodeMesh.frustumCulled = false

    return { lineObject, nodeMesh }
  }, [])

  useEffect(() => () => {
    lineObject.geometry.dispose()
    ;(lineObject.material as THREE.Material).dispose()
    nodeMesh.geometry.dispose()
    ;(nodeMesh.material as THREE.Material).dispose()
  }, [lineObject, nodeMesh])

  useFrame(() => {
    const t = entityUniforms.clock.value as number
    if (holder.current) {
      holder.current.rotation.y = -t * 0.025
      holder.current.rotation.z = Math.sin(t * 0.03) * 0.1
    }
  })

  return (
    <group ref={holder}>
      <primitive object={lineObject} />
      <primitive object={nodeMesh} />
    </group>
  )
}
