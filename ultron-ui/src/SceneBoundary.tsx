import { Component, type ReactNode } from 'react'

type State = { failed: boolean }

// Keeps a renderer failure (no WebGPU, lost GPU device) from unmounting the
// whole app, so the operations panel stays usable without the 3D entity.
export default class SceneBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error('[ULTRON] 3D scene stopped', error)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div style={{ position: 'fixed', inset: 0, display: 'grid', placeItems: 'center', background: '#000003', color: '#8d8a9a', font: '13px system-ui, sans-serif', padding: 16, textAlign: 'center' }}>
        3D view unavailable in this browser (WebGPU failed to start). The operations panel still works.
      </div>
    )
  }
}
