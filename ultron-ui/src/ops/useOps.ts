import { useCallback, useEffect, useRef, useState } from 'react'
import { wsconnect, type NatsConnection } from '@nats-io/nats-core'

// Subjects answered by the brain (src/ultron/control/operations.py).
const STATUS_SUBJECT = 'ultron.ops.status'
const STOP_SUBJECT = 'ultron.ops.stop'
const INTENT_SUBJECT = 'ultron.intent'
const VOICE_SUBJECT = 'ultron.voice'
// Answered by the vision service (src/ultron/agents/vision_service.py).
const VISION_CONTROL_SUBJECT = 'ultron.vision.control'
const VISION_STATE_SUBJECT = 'ultron.vision.state'

const NATS_WS_URL =
  import.meta.env.VITE_ULTRON_NATS_WS_URL ?? 'ws://127.0.0.1:9222'

const POLL_MS = 2000
const REQUEST_TIMEOUT_MS = 1500
const TRANSCRIPT_LIMIT = 60

export type ComponentHealth = { online: boolean; lastSeen: number | null }
export type ServiceHealth = { ok: boolean; detail: string }

export type TaskStep = { name: string; state: string; detail: string | null }

export type CurrentTask = {
  taskId: string
  prompt: string
  stage: string
  startedAt: number
  steps: TaskStep[]
}

export type RecentTask = {
  taskId: string
  prompt: string
  status: string
  result: string
  error: string | null
  updatedAt: string
}

export type OpsSnapshot = {
  observedAt: number
  components: Record<string, ComponentHealth>
  services: Record<string, ServiceHealth>
  current: CurrentTask | null
  queued: number
  recent: RecentTask[]
}

export type TranscriptEntry = {
  id: string
  role: 'you' | 'ultron'
  text: string
  at: number
  fromDashboard?: boolean
  ok?: boolean
  cancelled?: boolean
}

export type VisionState = { gesture: boolean; camera: boolean; error: string | null }

function parseVision(data: Record<string, unknown> | null): VisionState | null {
  if (!data || typeof data.gesture !== 'boolean') return null
  return {
    gesture: data.gesture,
    camera: data.camera === true,
    error: typeof data.error === 'string' && data.error ? data.error : null,
  }
}

// 'offline': no bus connection. 'no-brain': bus is up but the brain does not answer.
export type Link = 'connecting' | 'offline' | 'no-brain' | 'online'

let entryCounter = 0
const nextId = () => `e${Date.now()}-${entryCounter++}`

function readJson(data: Uint8Array): Record<string, unknown> | null {
  try {
    const value = JSON.parse(new TextDecoder().decode(data))
    return value && typeof value === 'object' ? value : null
  } catch {
    return null
  }
}

export function useOps(enabled: boolean) {
  const [link, setLink] = useState<Link>('connecting')
  const [snapshot, setSnapshot] = useState<OpsSnapshot | null>(null)
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  // null: the vision service has not been heard from.
  const [vision, setVision] = useState<VisionState | null>(null)
  const connection = useRef<NatsConnection | null>(null)

  const addEntry = useCallback((entry: Omit<TranscriptEntry, 'id' | 'at'>) => {
    setTranscript((items) =>
      [...items, { ...entry, id: nextId(), at: Date.now() }].slice(-TRANSCRIPT_LIMIT),
    )
  }, [])

  useEffect(() => {
    if (!enabled) return
    let disposed = false
    let poll: number | undefined

    const refresh = async () => {
      const nc = connection.current
      if (!nc || nc.isClosed()) return
      try {
        const reply = await nc.request(STATUS_SUBJECT, '{}', { timeout: REQUEST_TIMEOUT_MS })
        const data = readJson(reply.data)
        if (!disposed && data) {
          setSnapshot(data as unknown as OpsSnapshot)
          setLink('online')
        }
      } catch {
        // No responder or timeout: the bus works but the brain is not answering.
        if (!disposed) setLink((current) => (current === 'offline' ? current : 'no-brain'))
      }
    }

    const listen = async (nc: NatsConnection, subject: string, role: 'you' | 'ultron') => {
      for await (const message of nc.subscribe(subject)) {
        if (disposed) break
        const payload = readJson(message.data)
        if (!payload) continue
        if (role === 'you') {
          const prompt = typeof payload.prompt === 'string' ? payload.prompt.trim() : ''
          if (prompt) addEntry({ role, text: prompt, fromDashboard: payload.source === 'dashboard' })
        } else {
          const text = typeof payload.text === 'string' ? payload.text.trim() : ''
          const execution = payload.execution as { success?: boolean } | undefined
          if (text) {
            addEntry({
              role,
              text,
              ok: execution?.success,
              cancelled: payload.cancelled === true,
            })
          }
        }
      }
    }

    const watchVision = async (nc: NatsConnection) => {
      for await (const message of nc.subscribe(VISION_STATE_SUBJECT)) {
        if (disposed) break
        const state = parseVision(readJson(message.data))
        if (state) setVision(state)
      }
    }

    const askVision = async (nc: NatsConnection) => {
      try {
        const reply = await nc.request(VISION_CONTROL_SUBJECT, JSON.stringify({ command: 'status', source: 'ops' }), {
          timeout: REQUEST_TIMEOUT_MS,
        })
        const state = parseVision(readJson(reply.data))
        if (!disposed && state) setVision(state)
      } catch {
        if (!disposed) setVision(null)
      }
    }

    const watchStatus = async (nc: NatsConnection) => {
      for await (const status of nc.status()) {
        if (disposed) break
        if (status.type === 'disconnect' || status.type === 'reconnecting') setLink('offline')
        if (status.type === 'reconnect') {
          void refresh()
          void askVision(nc)
        }
      }
    }

    const start = async () => {
      try {
        const nc = await wsconnect({
          servers: [NATS_WS_URL],
          name: 'ultron-ops-panel',
          reconnect: true,
          maxReconnectAttempts: -1,
          reconnectTimeWait: 2000,
          waitOnFirstConnect: true,
          timeout: 10000,
          ignoreClusterUpdates: true,
        })
        if (disposed) {
          await nc.close()
          return
        }
        connection.current = nc
        void listen(nc, INTENT_SUBJECT, 'you')
        void listen(nc, VOICE_SUBJECT, 'ultron')
        void watchStatus(nc)
        void watchVision(nc)
        void askVision(nc)
        await refresh()
        poll = window.setInterval(() => void refresh(), POLL_MS)
      } catch {
        if (!disposed) setLink('offline')
      }
    }

    void start()

    return () => {
      disposed = true
      window.clearInterval(poll)
      const nc = connection.current
      connection.current = null
      if (nc) void nc.drain().catch(() => void nc.close())
    }
  }, [enabled, addEntry])

  const sendCommand = useCallback((prompt: string) => {
    const nc = connection.current
    const text = prompt.trim()
    if (!nc || nc.isClosed() || !text) return false
    nc.publish(
      INTENT_SUBJECT,
      JSON.stringify({ prompt: text.slice(0, 1000), requestId: nextId(), source: 'dashboard' }),
    )
    return true
  }, [])

  const stop = useCallback(async () => {
    const nc = connection.current
    if (!nc || nc.isClosed()) {
      setNotice('Not connected to Ultron.')
      return
    }
    try {
      const reply = await nc.request(STOP_SUBJECT, '{}', { timeout: REQUEST_TIMEOUT_MS })
      const data = readJson(reply.data) ?? {}
      const parts = [data.stoppedTask ? 'Current task will stop before its next step.' : 'No task was running.']
      if (typeof data.clearedQueued === 'number' && data.clearedQueued > 0) {
        parts.push(`${data.clearedQueued} queued request(s) dropped.`)
      }
      parts.push('Speech stopped.')
      setNotice(parts.join(' '))
    } catch {
      setNotice('The brain did not answer the stop request.')
    }
  }, [])

  const toggleGesture = useCallback(async () => {
    const nc = connection.current
    if (!nc || nc.isClosed()) {
      setNotice('Not connected to Ultron.')
      return
    }
    try {
      const reply = await nc.request(
        VISION_CONTROL_SUBJECT,
        JSON.stringify({ command: 'gesture_toggle', source: 'ops' }),
        { timeout: REQUEST_TIMEOUT_MS },
      )
      const state = parseVision(readJson(reply.data))
      if (state) {
        setVision(state)
        if (state.error) setNotice(`Gesture mode could not start: ${state.error}`)
      }
    } catch {
      setVision(null)
      setNotice('The vision service is not running. Start Ultron with the vision service to use gestures.')
    }
  }, [])

  return { link, snapshot, transcript, notice, setNotice, sendCommand, stop, vision, toggleGesture }
}
