import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import { hudView, sameView } from '../src/ops/gestureHudView.ts'

const base = { gestureMode: true, gestureError: null, gestureErrorAt: -Infinity, lastGesture: null, handsVisible: 1, now: 10 }

describe('gesture HUD', () => {
  test('hidden while gesture mode is off', () => {
    assert.equal(hudView({ ...base, gestureMode: false }).visible, false)
  })

  test('shows the latest pose, dimming once it is old', () => {
    const view = hudView({ ...base, lastGesture: { hand: 'Right', pose: 'thumbs_up', at: 9.5 } })
    assert.equal(view.title, 'Gesture mode')
    assert.equal(view.pose, 'Right · thumbs up')
    assert.equal(view.stale, false)
    assert.equal(hudView({ ...base, lastGesture: { hand: 'Right', pose: 'fist', at: 1 } }).stale, true)
    assert.equal(hudView({ ...base, lastGesture: { hand: 'Left', pose: 'unknown', at: 9.9 } }).pose, null)
  })

  test('asks for hands when none are in view', () => {
    assert.equal(hudView({ ...base, handsVisible: 0 }).pose, 'Show me your hands')
  })

  test('a camera error shows for a few seconds, then clears', () => {
    const error = { ...base, gestureMode: false, gestureError: 'Camera 0 could not be opened', gestureErrorAt: 8 }
    assert.equal(hudView(error).visible, true)
    assert.equal(hudView(error).error, 'Camera 0 could not be opened')
    assert.equal(hudView({ ...error, now: 30 }).visible, false)
  })

  test('views compare by what they show', () => {
    assert.ok(sameView(hudView(base), hudView({ ...base, now: 10.1 })))
    assert.ok(!sameView(hudView(base), hudView({ ...base, handsVisible: 0 })))
  })
})
