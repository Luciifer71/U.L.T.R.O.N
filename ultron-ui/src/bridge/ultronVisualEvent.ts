/* =========================================================
   ULTRON VISUAL EVENT CONTRACT

   External semantic events that are allowed to drive the
   visual entity.

   This file is intentionally framework-independent.
   ========================================================= */

export const ULTRON_VISUAL_SUBJECT = 'ultron.visual' as const

export const ULTRON_VISUAL_MODES = [
  'offline',
  'starting',
  'idle',
  'listening',
  'thinking',
  'executing',
  'alert',
  'focus',
  'sleep',
] as const

export type UltronVisualMode =
  (typeof ULTRON_VISUAL_MODES)[number]

export interface UltronVisualEvent {
  readonly event: UltronVisualMode
  readonly source: string
  readonly timestamp: number
  readonly eventId?: string
  readonly taskId?: string
}

export function isUltronVisualMode(
  value: unknown,
): value is UltronVisualMode {
  return (
    typeof value === 'string' &&
    (ULTRON_VISUAL_MODES as readonly string[]).includes(value)
  )
}

export function parseUltronVisualEvent(
  payload: unknown,
): UltronVisualEvent | null {

  if (
    typeof payload !== 'object' ||
    payload === null
  ) {
    return null
  }

  const candidate = payload as Record<string, unknown>

  if (!isUltronVisualMode(candidate.event)) {
    return null
  }

  if (
    typeof candidate.source !== 'string' ||
    candidate.source.trim().length === 0
  ) {
    return null
  }

  if (
    typeof candidate.timestamp !== 'number' ||
    !Number.isFinite(candidate.timestamp)
  ) {
    return null
  }

  return {
    event: candidate.event,
    source: candidate.source,
    timestamp: candidate.timestamp,
    ...(typeof candidate.eventId === 'string'
      ? { eventId: candidate.eventId }
      : {}),
    ...(typeof candidate.taskId === 'string'
      ? { taskId: candidate.taskId }
      : {}),
  }
}