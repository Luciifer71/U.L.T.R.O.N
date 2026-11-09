// The active scene is the WebGPU/TSL entity. Legacy WebGL scene files and the
// unmounted RenderRuntime are kept while renderer performance is investigated
// (see README); the previous WebGL App lives in App.backup.tsx.
import WebGPUTest from './WebGPUTest'
import SceneBoundary from './SceneBoundary'
import OpsPanel from './ops/OpsPanel'

export default function App() {
  return (
    <>
      <SceneBoundary>
        <WebGPUTest />
      </SceneBoundary>
      <OpsPanel />
    </>
  )
}
