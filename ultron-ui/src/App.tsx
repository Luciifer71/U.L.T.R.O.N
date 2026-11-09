// The active scene is the WebGPU/TSL entity. Legacy WebGL scene files and the
// unmounted RenderRuntime are kept while renderer performance is investigated
// (see README); the previous WebGL App lives in App.backup.tsx.
import WebGPUTest from './WebGPUTest'

export default function App() {
  return <WebGPUTest />
}
