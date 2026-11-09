import { useEffect, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { RenderPipeline } from 'three/webgpu'
import { pass } from 'three/tsl'
import { bloom } from 'three/addons/tsl/display/BloomNode.js'
import { entityUniforms } from './entityUniforms'

/* =========================================================
   ENTITY GLOW
   Renders the scene through a bloom pass so bright lines and
   particles spill soft light around them, like the film's
   holograms. Taking over rendering with a positive useFrame
   priority stops React Three Fiber's default render.
   ========================================================= */

export default function EntityGlow() {
  const { gl, scene, camera } = useThree()
  const renderer = gl as unknown as THREE.WebGPURenderer

  const pipeline = useMemo(() => {
    const scenePass = pass(scene, camera)
    const color = scenePass.getTextureNode('output')
    const glow = bloom(color, 1, 0.55, 0.08)
    const result = new RenderPipeline(renderer)
    result.outputNode = color.add(glow)
    return { result, glow }
  }, [renderer, scene, camera])

  useEffect(() => () => pipeline.result.dispose(), [pipeline])

  useFrame(() => {
    // Brighter glow as the core energises (idle → executing).
    pipeline.glow.strength.value = 0.75 + (entityUniforms.coreGlow.value as number) * 0.65
    pipeline.result.render()
  }, 1)

  return null
}
