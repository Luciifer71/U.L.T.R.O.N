import * as THREE from 'three/webgpu'

import TSLParticleField
  from './scene/TSLParticleField'

import TSLCircuitField
  from './scene/TSLCircuitField'

import TSLComputationalShell
  from './scene/TSLComputationalShell'

import TSLInformationFlow
  from './scene/TSLInformationFlow'

import TSLEnergyEvents
  from './scene/EnergyEvents'

import TSLSingularityCore
  from './scene/TSLSingularityCore'

import SimulationRuntime
  from './simulation/SimulationRuntime'

import { UltronEventBridge } from './bridge/UltronEventBridge'

import UltronEntity from './scene/UltronEntity'
import FrameLimiter from './entity/FrameLimiter'

import {
  Canvas,
} from '@react-three/fiber'

// The new entity is the default. Open the UI with ?legacy=1 to see the
// earlier dot-field layers instead; they are unchanged and kept for reference.
const SHOW_LEGACY_LAYERS =
  new URLSearchParams(window.location.search).get('legacy') === '1'

export default function EntityCanvas() {


  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        background: '#000003',
      }}
    >

      <Canvas
        // Rendering is driven by FrameLimiter (60 fps cap by default).
        frameloop="never"
        camera={{
          position: [
            0,
            0,
            4.8,
          ],

          fov: 50,
        }}

        gl={async (props) => {

          const renderer =
            new THREE.WebGPURenderer({
              ...(props as THREE.WebGPURendererParameters),

              antialias:
                true,

              powerPreference:
                'high-performance',

              outputBufferType:
                THREE.HalfFloatType,
            })

          renderer.setPixelRatio(
            Math.min(
              window.devicePixelRatio,
              2,
            ),
          )

          await renderer.init()

          return renderer
        }}
      >
        <FrameLimiter />

        <UltronEventBridge />
        
        <SimulationRuntime />

        {SHOW_LEGACY_LAYERS ? (
          <>
            <TSLSingularityCore />
            <TSLParticleField />
            <TSLCircuitField />
            <TSLComputationalShell />
            <TSLInformationFlow />
            <TSLEnergyEvents />
          </>
        ) : (
          <UltronEntity />
        )}

      </Canvas>

    </div>
  )
}