import { useEffect } from 'react'
import { useThree } from '@react-three/fiber'
import { parseMaxFps } from './entityConfig'

/* =========================================================
   FRAME LIMITER
   Drives the canvas (frameloop="never") at no more than the
   configured rate, 60 fps by default. Without it the scene
   renders on every display refresh, e.g. 144 times a second
   on a 144 Hz monitor, for no visible gain. Browsers already
   stop requestAnimationFrame in hidden tabs, so a minimised
   UI costs nothing.
   ========================================================= */

const MAX_FPS = parseMaxFps(window.location.search)
// Small allowance so a 60 Hz display is not throttled to 30 by timer jitter.
const MIN_INTERVAL_MS = 1000 / MAX_FPS - 1.5

export default function FrameLimiter() {
  const advance = useThree((state) => state.advance)

  useEffect(() => {
    let handle = 0
    let last = 0
    const tick = (timestamp: number) => {
      handle = requestAnimationFrame(tick)
      if (timestamp - last < MIN_INTERVAL_MS) return
      last = timestamp
      advance(timestamp)
    }
    handle = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(handle)
  }, [advance])

  return null
}
