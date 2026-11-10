// Explicit extension so Node's test runner can load this module directly.
import { RING_COUNT } from './entityConfig.ts'

/* =========================================================
   LIVE SIGNALS
   Turns what ULTRON is really doing into smooth numbers the
   entity layers can read every frame:

     ultron.signal.step     → each task step lights its own ring
     ultron.signal.voice    → your voice level ripples the core
     ultron.status.speaking → the core pulses while ULTRON talks
     ultron.intent / voice  → words stream in, replies stream out
     ultron.signal.model    → neural cascades while the model thinks
     ultron.signal.vitals   → CPU / memory load becomes core pressure
     ultron.signal.gaze     → (optional camera) the entity notices you arrive
     ultron.signal.hands    → tracked hands for the holographic hands (gesture mode)
     ultron.signal.gesture  → recognised poses, shown in the gesture HUD
     ultron.vision.state    → whether gesture mode is on

   Display only: nothing here ever sends a message or acts.
   With no backend connected every value rests at zero and
   the entity simply shows its Phase A behaviour.
   ========================================================= */

export type RingStatus = 'idle' | 'running' | 'done' | 'failed' | 'skipped'

export type RingState = { status: RingStatus; since: number }

export type Packet = {
  slot: number
  spawn: number // seconds (same clock as update())
  inbound: boolean
  direction: [number, number, number]
  seed: number
}

export type TrackedHand = {
  side: 'Right' | 'Left'
  pose: string
  engaged: boolean
  pinch: number
  points: [number, number, number][]
}

export const PACKET_SLOTS = 48
const HANDS_STALE = 0.4 // seconds: hands not updated this long are hidden
const MAX_PACKETS_PER_MESSAGE = 18
const PACKET_STAGGER = 0.07 // seconds between packets of one message
const MODEL_TIMEOUT = 120 // seconds: clear a model "start" that never ended
const VOICE_TIMEOUT = 1.5 // seconds: a lost final level must not freeze the ripple
const GAZE_TIMEOUT = 2 // seconds without camera updates → nobody known to be there
const NOTICE_AFTER_ABSENCE = 4 // seconds away before arriving counts as "noticed"

/** Inner rings first, alternating, so a three-step task lights three spread-out rings. */
export const STEP_RING_ORDER = [0, 2, 4, 6, 1, 3, 5, 7].filter((ring) => ring < RING_COUNT)

const DONE_STATES = new Set(['verified', 'completed', 'dispatched'])
const SKIPPED_STATES = new Set(['cancelled', 'not_started'])

function approach(current: number, target: number, rate: number, dt: number) {
  return current + (target - current) * (1 - Math.exp(-rate * dt))
}

function clamp01(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0
}

function smoothstep(edge0: number, edge1: number, x: number) {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}

/** Validate tracked hands from the vision service; anything malformed is dropped. */
export function parseHands(value: unknown): TrackedHand[] {
  if (!Array.isArray(value)) return []
  const hands: TrackedHand[] = []
  for (const item of value.slice(0, 2)) {
    if (typeof item !== 'object' || item === null) continue
    const hand = item as Record<string, unknown>
    if (hand.side !== 'Right' && hand.side !== 'Left') continue
    const points = hand.points
    if (!Array.isArray(points) || points.length !== 21) continue
    const parsed = points.map((p) =>
      Array.isArray(p) && p.length >= 3 && p.slice(0, 3).every((v) => typeof v === 'number' && Number.isFinite(v))
        ? ([p[0], p[1], p[2]] as [number, number, number])
        : null,
    )
    if (parsed.some((p) => p === null)) continue
    hands.push({
      side: hand.side,
      pose: typeof hand.pose === 'string' ? hand.pose : 'unknown',
      engaged: hand.engaged === true,
      pinch: typeof hand.pinch === 'number' && Number.isFinite(hand.pinch) ? hand.pinch : 1,
      points: parsed as [number, number, number][],
    })
  }
  return hands
}

export function wordCount(text: unknown) {
  return typeof text === 'string' ? text.trim().split(/\s+/).filter(Boolean).length : 0
}

export function createLiveSignals(random: () => number = Math.random) {
  const state = {
    // Smoothed 0..1 values read by the renderer.
    voice: 0,
    speak: 0,
    model: 0,
    pressure: 0,
    // Raw inputs.
    voiceTarget: 0,
    voiceAt: -Infinity,
    speaking: false,
    modelActive: false,
    modelSince: 0,
    cpu: 0,
    memory: 0,
    taskId: null as string | null,
    /** Increments on every failed step, so effects can react once per failure. */
    failures: 0,
    // Camera presence (smoothed 0..1). The entity no longer follows the viewer;
    // presence is only used to notice someone arriving.
    presence: 0,
    gazeTarget: { present: false, x: 0, y: 0, at: -Infinity },
    absentSince: -Infinity,
    /** Increments when someone arrives after being away, so the entity can react once. */
    notices: 0,
    // Gesture mode.
    gestureMode: false,
    gestureError: null as string | null,
    gestureErrorAt: -Infinity,
    hands: [] as TrackedHand[],
    handsAt: -Infinity,
    lastGesture: null as { hand: string; pose: string; at: number } | null,
    rings: Array.from({ length: RING_COUNT }, (): RingState => ({ status: 'idle', since: -Infinity })),
    now: 0,
  }

  let nextSlot = 0
  let fresh: Packet[] = []

  function spawnPackets(text: unknown, inbound: boolean, now: number) {
    const count = Math.min(wordCount(text), MAX_PACKETS_PER_MESSAGE)
    for (let i = 0; i < count; i++) {
      const z = random() * 2 - 1
      const angle = random() * Math.PI * 2
      const ring = Math.sqrt(1 - z * z)
      fresh.push({
        slot: nextSlot,
        spawn: now + i * PACKET_STAGGER,
        inbound,
        direction: [Math.cos(angle) * ring, z, Math.sin(angle) * ring],
        seed: random(),
      })
      nextSlot = (nextSlot + 1) % PACKET_SLOTS
    }
  }

  function onStep(payload: Record<string, unknown>, now: number) {
    const taskId = typeof payload.taskId === 'string' ? payload.taskId : null
    const index = typeof payload.index === 'number' ? Math.max(0, Math.floor(payload.index)) : 0
    const stepState = typeof payload.state === 'string' ? payload.state : ''
    if (taskId !== state.taskId) {
      // A new task: earlier rings fall quiet.
      state.taskId = taskId
      for (const ring of state.rings) if (ring.status !== 'idle') ring.status = 'idle'
    }
    const ring = state.rings[STEP_RING_ORDER[index % STEP_RING_ORDER.length]]
    if (!ring) return
    const status: RingStatus =
      stepState === 'running' ? 'running'
        : DONE_STATES.has(stepState) ? 'done'
          : SKIPPED_STATES.has(stepState) ? 'skipped'
            : 'failed'
    ring.status = status
    ring.since = now
    if (status === 'failed') state.failures++
  }

  /** Feed one bus message. Unknown subjects and malformed payloads are ignored. */
  function handle(subject: string, payload: unknown, now: number) {
    if (typeof payload !== 'object' || payload === null) return
    const data = payload as Record<string, unknown>
    switch (subject) {
      case 'ultron.signal.step':
        onStep(data, now)
        break
      case 'ultron.signal.voice':
        state.voiceTarget = clamp01(data.level)
        state.voiceAt = now
        break
      case 'ultron.status.speaking':
        state.speaking = data.speaking === true
        break
      case 'ultron.signal.model':
        if (data.phase === 'start') {
          state.modelActive = true
          state.modelSince = now
        } else if (data.phase === 'end') {
          state.modelActive = false
        }
        break
      case 'ultron.signal.vitals':
        state.cpu = clamp01(data.cpu)
        state.memory = clamp01(data.memory)
        break
      case 'ultron.signal.gaze': {
        const present = data.present === true
        const target = state.gazeTarget
        if (present && !target.present && now - state.absentSince > NOTICE_AFTER_ABSENCE) state.notices++
        if (!present && target.present) state.absentSince = now
        target.present = present
        target.x = Math.max(-1, Math.min(1, typeof data.x === 'number' && Number.isFinite(data.x) ? data.x : 0))
        target.y = Math.max(-1, Math.min(1, typeof data.y === 'number' && Number.isFinite(data.y) ? data.y : 0))
        target.at = now
        break
      }
      case 'ultron.signal.hands':
        state.hands = parseHands(data.hands)
        state.handsAt = now
        break
      case 'ultron.signal.gesture':
        if (data.type === 'pose' && typeof data.pose === 'string' && typeof data.hand === 'string') {
          state.lastGesture = { hand: data.hand, pose: data.pose, at: now }
        }
        break
      case 'ultron.vision.state': {
        const wasOn = state.gestureMode
        state.gestureMode = data.gesture === true
        state.gestureError = typeof data.error === 'string' && data.error ? data.error : null
        if (state.gestureError) state.gestureErrorAt = now
        if (state.gestureMode && !wasOn) state.lastGesture = null
        if (!state.gestureMode) state.hands = []
        break
      }
      case 'ultron.intent':
        spawnPackets(data.prompt, true, now)
        break
      case 'ultron.voice':
        spawnPackets(data.text, false, now)
        break
    }
  }

  /** Advance smoothing to time `now` (seconds). */
  function update(now: number, dt: number) {
    state.now = now
    if (state.modelActive && now - state.modelSince > MODEL_TIMEOUT) state.modelActive = false
    if (now - state.voiceAt > VOICE_TIMEOUT) state.voiceTarget = 0

    // Voice: fast attack, slower release, like a VU meter.
    state.voice = approach(state.voice, state.voiceTarget, state.voiceTarget > state.voice ? 25 : 6, dt)

    // Speech has no amplitude feed, so speaking drives a syllable-like rhythm.
    const syllables = 0.55 + 0.45 * Math.sin(now * 11.0) * Math.sin(now * 3.7 + 1.3)
    state.speak = approach(state.speak, state.speaking ? Math.max(0.15, syllables) : 0, 14, dt)

    // Model thinking builds up over the first few seconds of a request.
    const modelTarget = state.modelActive ? Math.min(1, 0.4 + (now - state.modelSince) * 0.2) : 0
    state.model = approach(state.model, modelTarget, 3, dt)

    // Camera presence: lost updates (camera stopped) count as nobody there.
    const gaze = state.gazeTarget
    if (gaze.present && now - gaze.at > GAZE_TIMEOUT) {
      gaze.present = false
      state.absentSince = now
    }
    state.presence = approach(state.presence, gaze.present ? 1 : 0, 1.5, dt)
    if (now - state.handsAt > HANDS_STALE) state.hands = []

    // Only real strain shows: high CPU, or memory close to full.
    const strain = Math.max(smoothstep(0.55, 0.95, state.cpu), smoothstep(0.88, 0.99, state.memory) * 0.6)
    state.pressure = approach(state.pressure, strain, 0.8, dt)
  }

  /** Packets spawned since the last call (the renderer writes them to the GPU). */
  function takeNewPackets() {
    const out = fresh
    fresh = []
    return out
  }

  return { state, handle, update, takeNewPackets }
}

export const liveSignals = createLiveSignals()
