/* What the gesture HUD shows, as a pure function of the live signal state. */

export type HudInput = {
  gestureMode: boolean
  gestureError: string | null
  gestureErrorAt: number
  lastGesture: { hand: string; pose: string; at: number } | null
  handsVisible: number
  now: number
}

export type HudView = {
  visible: boolean
  title: string
  pose: string | null
  stale: boolean
  error: string | null
}

const POSE_FRESH = 2.5 // seconds a recognised pose stays bright
const ERROR_SHOWN = 8 // seconds a "could not start" message stays up

export function poseLabel(pose: string) {
  return pose.replace(/_/g, ' ')
}

export function hudView(input: HudInput): HudView {
  const error = input.gestureError && input.now - input.gestureErrorAt < ERROR_SHOWN ? input.gestureError : null
  if (!input.gestureMode) {
    return { visible: !!error, title: 'Gesture mode off', pose: null, stale: false, error }
  }
  const last = input.lastGesture
  const pose = last && last.pose !== 'unknown' ? `${last.hand} · ${poseLabel(last.pose)}` : null
  const fresh = !!last && input.now - last.at < POSE_FRESH
  return {
    visible: true,
    title: 'Gesture mode',
    pose: input.handsVisible === 0 ? 'Show me your hands' : pose,
    stale: input.handsVisible === 0 || !fresh,
    error: null,
  }
}

export function sameView(a: HudView, b: HudView) {
  return a.visible === b.visible && a.title === b.title && a.pose === b.pose && a.stale === b.stale && a.error === b.error
}
