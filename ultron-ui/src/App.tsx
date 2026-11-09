// Earlier WebGL draft of the entity scene (breathing core motion, bloom,
// radial background). Kept as design reference for the future entity UI.

// import { Canvas, useFrame } from '@react-three/fiber'
// import { Bloom, EffectComposer } from '@react-three/postprocessing'
// import { useRef } from 'react'
// import * as THREE from 'three'
// import SingularityCore from './scene/SingularityCore'
// import ParticleHalo from './scene/EntityParticles'
// import NeuralFilaments from './scene/CircuitField'
// import RenderRuntime from './render/RenderRuntime'

// /* =========================================================
//    CORE MOTION
//    ========================================================= */

// function CoreMotion() {

//   const groupRef =
//     useRef<THREE.Group>(null)

//   useFrame(
//     (state) => {

//       if (
//         !groupRef.current
//       )
//         return

//       const time =
//         state.clock.elapsedTime

//       groupRef.current.rotation.y =
//         time *
//         0.045

//       groupRef.current.rotation.x =
//         Math.sin(
//           time *
//           0.16
//         ) *
//         0.075

//       groupRef.current.rotation.z =
//         Math.cos(
//           time *
//           0.11
//         ) *
//         0.045

//       const pulse =
//         1 +
//         Math.sin(
//           time *
//           1.5
//         ) *
//         0.012

//       groupRef.current.scale.setScalar(
//         pulse,
//       )
//     },
//   )

//   return (
//   <group ref={groupRef}>
//     <ParticleHalo />
//     <NeuralFilaments />
//     <SingularityCore />
//   </group>
// )
// }

// /* =========================================================
//    SCENE
//    ========================================================= */

// function Scene() {

//   return (
//     <>
//       <CoreMotion />

//       <ambientLight
//         intensity={
//           0.015
//         }
//       />

//       <pointLight
//         color="#143eff"
//         intensity={2.5}
//         distance={5}
//       />

//       <EffectComposer>

//         <Bloom
//           intensity={
//             1.35
//           }
//           luminanceThreshold={
//             0.45
//           }
//           luminanceSmoothing={
//             0.9
//           }
//           mipmapBlur
//         />

//       </EffectComposer>
//     </>
//   )
// }

// /* =========================================================
//    APP
//    ========================================================= */

// function App() {

//   return (
//     <div
//       style={{
//         width: '100vw',
//         height: '100vh',
//         overflow: 'hidden',

//         background:
//           'radial-gradient(circle at center, #03040b 0%, #000106 52%, #000000 100%)',
//       }}
//     >

//       <Canvas
//         camera={{
//           position: [
//             0,
//             0,
//             5.4,
//           ],
//           fov: 48,
//         }}

//         dpr={[
//           1,
//           2,
//         ]}

//         gl={{
//           antialias:
//             true,

//           powerPreference:
//             'high-performance',

//           toneMapping:
//             THREE.ACESFilmicToneMapping,

//           toneMappingExposure:
//             1.0,
//         }}
//       >
//         <RenderRuntime />
//         <Scene />

//       </Canvas>

//     </div>
//   )
// }

// export default App

// The active scene is the WebGPU/TSL entity. Legacy WebGL scene files and the
// unmounted RenderRuntime are kept while renderer performance is investigated
// (see README); the previous WebGL App lives in App.backup.tsx.
import EntityCanvas from './EntityCanvas'
import SceneBoundary from './SceneBoundary'
import OpsPanel from './ops/OpsPanel'

export default function App() {
  return (
    <>
      <SceneBoundary>
        <EntityCanvas />
      </SceneBoundary>
      <OpsPanel />
    </>
  )
}
