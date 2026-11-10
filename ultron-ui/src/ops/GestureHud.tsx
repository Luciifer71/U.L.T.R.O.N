import { useEffect, useState } from 'react'
import { liveSignals } from '../entity/liveSignals'
import { hudView, sameView, type HudView } from './gestureHud'

/* =========================================================
   GESTURE HUD
   A small "GESTURE MODE" title over the entity while gesture
   mode is on, with the pose last recognised. It polls the live
   signal store a few times a second and only re-renders when
   what it shows changes.
   ========================================================= */

const POLL_MS = 150

function read(): HudView {
  const s = liveSignals.state
  return hudView({
    gestureMode: s.gestureMode,
    gestureError: s.gestureError,
    gestureErrorAt: s.gestureErrorAt,
    lastGesture: s.lastGesture,
    handsVisible: s.hands.length,
    now: performance.now() / 1000,
  })
}

export default function GestureHud() {
  const [view, setView] = useState(read)

  useEffect(() => {
    const timer = window.setInterval(() => {
      const next = read()
      setView((current) => (sameView(current, next) ? current : next))
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [])

  if (!view.visible) return null
  return (
    <div className="gesture-hud" role="status" aria-live="polite">
      {view.error ? (
        <span className="gesture-hud-error">Gesture mode stopped: {view.error}</span>
      ) : (
        <>
          <span className="gesture-hud-title">{view.title}</span>
          {view.pose && <span className={`gesture-hud-pose${view.stale ? ' gesture-hud-pose--stale' : ''}`}>{view.pose}</span>}
        </>
      )}
    </div>
  )
}
