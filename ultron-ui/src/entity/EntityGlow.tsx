import { useEffect, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three/webgpu'
import { RenderPipeline } from 'three/webgpu'
import { exp, float, floor, fract, max, pass, screenUV, sin, smoothstep, step, uniform, vec2, vec3, vec4 } from 'three/tsl'
import type { Node, TextureNode } from 'three/webgpu'
import { bloom } from 'three/addons/tsl/display/BloomNode.js'
import { entityUniforms, stateColor } from './entityUniforms'

/* =========================================================
   ENTITY GLOW + LENS
   Renders the scene once, blooms it, then composites through
   a single "camera lens" pass that makes it feel filmed:

     gravitational lensing  the core bends the light around it
     chromatic aberration   colours split toward the frame edges
     anamorphic streak      horizontal flare from the brightest light
     glitch                 slice tearing + colour split bursts
     hologram scan          an occasional bright scan line
     vignette + grain       darker corners, faint living film grain

   One extra full-screen pass, a handful of texture reads per
   pixel: cheap next to the scene itself.
   ========================================================= */

const STREAK_TAPS = 6

function hash(value: Node<'float'>) {
  return fract(sin(value.mul(12.9898)).mul(43758.5453))
}

export default function EntityGlow() {
  const { gl, scene, camera, size } = useThree()
  const renderer = gl as unknown as THREE.WebGPURenderer
  const aspect = useMemo(() => uniform(1), [])
  const lens = useMemo(() => uniform(0.6), [])

  const pipeline = useMemo(() => {
    const { glitch, scan, now } = entityUniforms
    const scenePass = pass(scene, camera)
    const sceneTex = scenePass.getTextureNode('output')
    const glow = bloom(sceneTex, 1, 0.55, 0.08)
    // BloomNode exposes its blurred result as a texture node (missing from the typings).
    const glowTex = (glow as unknown as { getTextureNode(): TextureNode }).getTextureNode()

    // ---- glitch: horizontal slices jump sideways during a burst
    const band = floor(screenUV.y.mul(42.0)).add(floor(now.mul(24.0)).mul(13.0))
    const tear = step(float(1).sub(glitch.mul(0.55)), hash(band.add(5.3)))
    const slice = hash(band).sub(0.5).mul(0.07).mul(glitch).mul(tear)
    const uvGlitch = vec2(screenUV.x.add(slice), screenUV.y)

    // ---- gravitational lensing toward the core at the frame centre
    const offset = uvGlitch.sub(0.5)
    const scaled = vec2(offset.x.mul(aspect), offset.y)
    const radius = max(scaled.length(), float(0.0001))
    // Bending is confined to a ring around the core (not over the core itself,
    // which would just magnify it), strongest just outside its glow.
    const ringMask = smoothstep(0.08, 0.16, radius).mul(float(1).sub(smoothstep(0.16, 0.46, radius)))
    const pull = lens.mul(0.014).mul(ringMask)
    // Sample closer to the core: light from behind it appears bent outward.
    const uvLens = uvGlitch.sub(offset.div(radius).mul(pull))

    // ---- chromatic aberration grows toward the edges and during glitches
    const edge = offset.length()
    const split = offset.mul(float(0.006).mul(edge).add(glitch.mul(0.012)))
    const red = sceneTex.sample(uvLens.add(split)).r.add(glowTex.sample(uvLens.add(split)).r)
    const green = sceneTex.sample(uvLens).g.add(glowTex.sample(uvLens).g)
    const blue = sceneTex.sample(uvLens.sub(split)).b.add(glowTex.sample(uvLens.sub(split)).b)
    let color: Node<'vec3'> = vec3(red, green, blue)

    // ---- anamorphic streak: a thin horizontal flare from bright highlights
    let streak: Node<'vec3'> = vec3(0, 0, 0)
    for (let i = 1; i <= STREAK_TAPS; i++) {
      const dx = vec2(i * 0.018, 0)
      const tap = glowTex.sample(uvLens.add(dx)).rgb.add(glowTex.sample(uvLens.sub(dx)).rgb)
      streak = streak.add(tap.mul(1 / (i * 1.6)))
    }
    const streakLuma = streak.dot(vec3(0.33, 0.33, 0.34))
    color = color.add(stateColor().mul(0.5).add(vec3(0.15, 0.15, 0.2)).mul(streakLuma).mul(0.22))

    // ---- hologram scan line (only lights what is already bright)
    const scanBand = exp(screenUV.y.sub(float(1).sub(scan)).div(0.012).pow(2).negate())
    const brightness = color.dot(vec3(0.3, 0.5, 0.2))
    color = color.add(color.mul(scanBand.mul(0.7))).add(stateColor().mul(scanBand.mul(smoothstep(0.02, 0.3, brightness)).mul(0.25)))

    // ---- vignette and faint, moving film grain
    const corner = vec2(offset.x.mul(aspect), offset.y).length()
    const vignette = float(1).sub(smoothstep(0.35, 0.95, corner).mul(0.55))
    const grainSeed = screenUV.x.mul(1931.0).add(screenUV.y.mul(4271.0)).add(fract(now.mul(7.13)).mul(97.0))
    const grain = hash(grainSeed).sub(0.5).mul(0.02)
    color = color.mul(vignette).add(grain)

    const result = new RenderPipeline(renderer)
    result.outputNode = vec4(color, 1)
    return { result, glow }
  }, [renderer, scene, camera, aspect, lens])

  useEffect(() => () => pipeline.result.dispose(), [pipeline])

  useFrame(() => {
    const u = entityUniforms
    aspect.value = size.width / Math.max(1, size.height)
    // Brighter glow, and stronger light bending, as the core energises.
    pipeline.glow.strength.value = 0.75 + (u.coreGlow.value as number) * 0.65
    lens.value = 0.35 + (u.coreGlow.value as number) * 0.5 + (u.model.value as number) * 0.3
    pipeline.result.render()
  }, 1)

  return null
}
