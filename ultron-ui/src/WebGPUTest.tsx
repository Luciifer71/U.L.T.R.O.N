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

import {
  Canvas,
} from '@react-three/fiber'

export default function WebGPUTest() {

  console.log(
    '[ULTRON] WebGPUTest MOUNTED',
  )

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        background: '#000003',
      }}
    >

      <Canvas
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
        <UltronEventBridge />
        
        <SimulationRuntime />

        <TSLSingularityCore />

        <TSLParticleField />

        <TSLCircuitField />

        <TSLComputationalShell />

        <TSLInformationFlow />

        <TSLEnergyEvents />

      </Canvas>

    </div>
  )
}