import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseUltronVisualEvent, ULTRON_VISUAL_MODES } from '../src/bridge/ultronVisualEvent.ts'

test('accepts every documented mode', () => {
  for (const event of ULTRON_VISUAL_MODES) {
    assert.deepEqual(parseUltronVisualEvent({ event, source: 'brain', timestamp: 1, taskId: 't' }), {
      event,
      source: 'brain',
      timestamp: 1,
      taskId: 't',
    })
  }
})

test('rejects malformed or unknown events instead of guessing', () => {
  for (const payload of [
    null,
    'idle',
    {},
    { event: 'dance', source: 'brain', timestamp: 1 },
    { event: 'idle', source: '  ', timestamp: 1 },
    { event: 'idle', source: 'brain', timestamp: Number.NaN },
    { event: 'idle', source: 'brain' },
  ]) {
    assert.equal(parseUltronVisualEvent(payload), null, JSON.stringify(payload))
  }
})

test('drops unexpected fields', () => {
  const parsed = parseUltronVisualEvent({ event: 'idle', source: 'brain', timestamp: 1, action: 'lock_pc' })
  assert.ok(parsed && !('action' in parsed))
})
