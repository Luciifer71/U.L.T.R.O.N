import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { createLiveSignals, PACKET_SLOTS, parseHands, STEP_RING_ORDER, wordCount } from '../src/entity/liveSignals.ts'
import { RING_COUNT } from '../src/entity/entityConfig.ts'

function seeded(seed = 1) {
  let s = seed
  return () => {
    s = (s * 16807) % 2147483647
    return (s - 1) / 2147483646
  }
}

function settle(live: ReturnType<typeof createLiveSignals>, from: number, seconds: number) {
  let now = from
  for (let i = 0; i < seconds * 60; i++) {
    now += 1 / 60
    live.update(now, 1 / 60)
  }
  return now
}

describe('task steps', () => {
  test('each step of a task lights its own ring, spread out from the inside', () => {
    const live = createLiveSignals(seeded())
    for (let index = 0; index < 3; index++) {
      live.handle('ultron.signal.step', { taskId: 'a', index, total: 3, kind: 'open_resource', state: 'running' }, index)
    }
    const lit = live.state.rings.map((ring, i) => (ring.status === 'running' ? i : -1)).filter((i) => i >= 0)
    assert.deepEqual(lit, STEP_RING_ORDER.slice(0, 3).sort((a, b) => a - b))
  })

  test('outcomes map to done, failed and skipped', () => {
    const live = createLiveSignals(seeded())
    const cases: [string, string][] = [
      ['verified', 'done'], ['completed', 'done'], ['dispatched', 'done'],
      ['failed', 'failed'], ['preflight_failed', 'failed'],
      ['cancelled', 'skipped'], ['not_started', 'skipped'],
    ]
    for (const [state, status] of cases) {
      live.handle('ultron.signal.step', { taskId: 'a', index: 0, state }, 5)
      assert.equal(live.state.rings[STEP_RING_ORDER[0]].status, status, state)
      assert.equal(live.state.rings[STEP_RING_ORDER[0]].since, 5)
    }
  })

  test('a new task clears the rings of the previous one', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.signal.step', { taskId: 'a', index: 1, state: 'failed' }, 1)
    live.handle('ultron.signal.step', { taskId: 'b', index: 0, state: 'running' }, 2)
    const statuses = live.state.rings.map((ring) => ring.status)
    assert.equal(statuses.filter((s) => s !== 'idle').length, 1)
    assert.equal(statuses[STEP_RING_ORDER[0]], 'running')
  })

  test('more steps than rings wrap around instead of failing', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.signal.step', { taskId: 'a', index: RING_COUNT + 1, state: 'running' }, 1)
    assert.equal(live.state.rings[STEP_RING_ORDER[1]].status, 'running')
  })
})

describe('voice and speech', () => {
  test('voice level rises fast, falls slower, and settles if the final zero is lost', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.signal.voice', { level: 0.8 }, 0)
    let now = settle(live, 0, 0.15)
    assert.ok(live.state.voice > 0.7, `attack ${live.state.voice}`)
    live.handle('ultron.signal.voice', { level: 0 }, now)
    now = settle(live, now, 0.15)
    assert.ok(live.state.voice > 0.25, `release is slower: ${live.state.voice}`)
    live.handle('ultron.signal.voice', { level: 0.9 }, now)
    settle(live, now, 3) // no further messages arrive
    assert.ok(live.state.voice < 0.02, 'a stale level does not freeze the ripple')
  })

  test('speaking drives a pulsing envelope that stops when speech ends', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.status.speaking', { speaking: true, version: 1 }, 0)
    let min = 1
    let max = 0
    let now = settle(live, 0, 0.5)
    for (let i = 0; i < 120; i++) {
      now += 1 / 60
      live.update(now, 1 / 60)
      min = Math.min(min, live.state.speak)
      max = Math.max(max, live.state.speak)
    }
    assert.ok(max - min > 0.3, `envelope moves: ${min}..${max}`)
    live.handle('ultron.status.speaking', { speaking: false }, now)
    settle(live, now, 1)
    assert.ok(live.state.speak < 0.01)
  })
})

describe('model, vitals and words', () => {
  test('model activity builds up while thinking and clears on end or timeout', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.signal.model', { phase: 'start' }, 0)
    let now = settle(live, 0, 1)
    const early = live.state.model
    now = settle(live, now, 3)
    assert.ok(live.state.model > early, 'grows the longer the model thinks')
    live.handle('ultron.signal.model', { phase: 'end', seconds: 4 }, now)
    now = settle(live, now, 3)
    assert.ok(live.state.model < 0.01)
    live.handle('ultron.signal.model', { phase: 'start' }, now)
    settle(live, now, 125)
    assert.ok(live.state.model < 0.01, 'a lost "end" times out')
  })

  test('only real strain becomes pressure', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.signal.vitals', { cpu: 0.3, memory: 0.7 }, 0)
    let now = settle(live, 0, 10)
    assert.ok(live.state.pressure < 0.01, 'normal load stays calm')
    live.handle('ultron.signal.vitals', { cpu: 0.98, memory: 0.5 }, now)
    now = settle(live, now, 10)
    assert.ok(live.state.pressure > 0.9, 'a pegged CPU shows')
    live.handle('ultron.signal.vitals', { cpu: 'oops', memory: null }, now)
    settle(live, now, 10)
    assert.ok(live.state.pressure < 0.01, 'malformed values read as zero')
  })

  test('words become packets: in for requests, out for replies, capped and recycled', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.intent', { prompt: 'open calculator and notion please' }, 1)
    const inbound = live.takeNewPackets()
    assert.equal(inbound.length, 5)
    assert.ok(inbound.every((p) => p.inbound))
    assert.ok(inbound[4].spawn > inbound[0].spawn, 'staggered like a stream')
    assert.equal(live.takeNewPackets().length, 0, 'taken once')

    live.handle('ultron.voice', { text: 'word '.repeat(100) }, 2)
    const outbound = live.takeNewPackets()
    assert.ok(outbound.length <= 18 && outbound.every((p) => !p.inbound))
    assert.ok(outbound.every((p) => p.slot >= 0 && p.slot < PACKET_SLOTS))
    for (const p of outbound) {
      const [x, y, z] = p.direction
      assert.ok(Math.abs(Math.hypot(x, y, z) - 1) < 1e-9)
    }
  })

  test('ignores junk and unrelated subjects', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.signal.step', null, 0)
    live.handle('ultron.visual', { event: 'idle' }, 0)
    live.handle('ultron.voice', { text: 42 }, 0)
    assert.equal(live.takeNewPackets().length, 0)
    assert.ok(live.state.rings.every((ring) => ring.status === 'idle'))
    assert.equal(wordCount('  two   words '), 2)
  })
})

describe('camera presence', () => {
  test('arriving is noticed once and presence fades when they leave', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.signal.gaze', { present: true, x: 0.8, y: -0.4, near: 0.3 }, 0)
    assert.equal(live.state.notices, 1, 'the first arrival is noticed')
    let now = 0
    for (let i = 0; i < 4 * 60; i++) {
      now += 1 / 60
      if (i % 6 === 0) live.handle('ultron.signal.gaze', { present: true, x: 0.8, y: -0.4 }, now)
      live.update(now, 1 / 60)
    }
    assert.ok(live.state.presence > 0.95)
    live.handle('ultron.signal.gaze', { present: true, x: 0.8, y: -0.4 }, now)
    assert.equal(live.state.notices, 1, 'staying present is not noticed again')

    live.handle('ultron.signal.gaze', { present: false, x: 0, y: 0 }, now)
    now = settle(live, now, 5)
    assert.ok(live.state.presence < 0.01, 'presence fades when they leave')
    live.handle('ultron.signal.gaze', { present: true, x: 0, y: 0 }, now)
    assert.equal(live.state.notices, 2, 'coming back after a while is noticed')
  })

  test('a quick step out of frame is not a new arrival, and a stopped camera times out', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.signal.gaze', { present: true, x: 0, y: 0 }, 0)
    live.handle('ultron.signal.gaze', { present: false }, 1)
    live.handle('ultron.signal.gaze', { present: true, x: 0, y: 0 }, 2)
    assert.equal(live.state.notices, 1)
    settle(live, 2, 3) // no further messages: the watcher stopped
    assert.equal(live.state.gazeTarget.present, false)
    live.handle('ultron.signal.gaze', { present: true, x: 'left', y: Number.NaN }, 20)
    assert.equal(live.state.gazeTarget.x, 0)
    assert.equal(live.state.gazeTarget.y, 0)
  })
})

describe('gesture mode', () => {
  const hand = (side: string, pose = 'point') => ({
    side, pose, engaged: true, pinch: 0.8,
    points: Array.from({ length: 21 }, (_, i) => [0.4 + i * 0.005, 0.5 - i * 0.01, 0]),
  })

  test('vision state, hands and poses are tracked; hands vanish when stale or mode ends', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.vision.state', { gesture: true, presence: false, camera: true, error: null }, 0)
    assert.equal(live.state.gestureMode, true)
    live.handle('ultron.signal.hands', { hands: [hand('Right'), hand('Left', 'open_palm')] }, 0.1)
    assert.equal(live.state.hands.length, 2)
    live.handle('ultron.signal.gesture', { type: 'pose', hand: 'Right', pose: 'pinch', previous: 'point' }, 0.2)
    assert.deepEqual(live.state.lastGesture, { hand: 'Right', pose: 'pinch', at: 0.2 })
    live.update(1, 1 / 60)
    assert.equal(live.state.hands.length, 0, 'stale hands are hidden')
    live.handle('ultron.signal.hands', { hands: [hand('Right')] }, 1)
    live.handle('ultron.vision.state', { gesture: false, error: 'Camera 0 could not be opened' }, 1.1)
    assert.equal(live.state.gestureMode, false)
    assert.equal(live.state.gestureError, 'Camera 0 could not be opened')
    assert.equal(live.state.hands.length, 0)
    assert.equal(live.state.gestureErrorAt, 1.1)
  })

  test('turning gesture mode on clears the pose from last time', () => {
    const live = createLiveSignals(seeded())
    live.handle('ultron.vision.state', { gesture: true }, 0)
    live.handle('ultron.signal.gesture', { type: 'pose', hand: 'Right', pose: 'fist', previous: 'point' }, 1)
    live.handle('ultron.vision.state', { gesture: false }, 2)
    live.handle('ultron.vision.state', { gesture: true }, 3)
    assert.equal(live.state.lastGesture, null)
  })

  test('malformed hands are dropped, never drawn', () => {
    assert.deepEqual(parseHands('nope'), [])
    assert.equal(parseHands([hand('Middle')]).length, 0)
    assert.equal(parseHands([{ ...hand('Right'), points: [[0, 0, 0]] }]).length, 0)
    assert.equal(parseHands([{ ...hand('Right'), points: Array(21).fill([0, 'x', 0]) }]).length, 0)
    assert.equal(parseHands([hand('Right'), hand('Left'), hand('Right')]).length, 2, 'at most two hands')
  })
})
