import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import {
  createHandBuffers, HAND_CONNECTIONS, JOINTS, LINE_VERTICES, pinchGlow, slotOf, toScene, writeHand,
} from '../src/entity/handSkeleton.ts'
import type { TrackedHand } from '../src/entity/liveSignals.ts'

const hand = (overrides: Partial<TrackedHand> = {}): TrackedHand => ({
  side: 'Right',
  pose: 'point',
  engaged: true,
  pinch: 0.9,
  points: Array.from({ length: 21 }, (_, i) => [0.3 + i * 0.01, 0.6 - i * 0.01, -i * 0.002] as [number, number, number]),
  ...overrides,
})

describe('holo hands', () => {
  test('the skeleton matches the 21 MediaPipe landmarks', () => {
    assert.equal(HAND_CONNECTIONS.length, 21)
    for (const [a, b] of HAND_CONNECTIONS) {
      assert.ok(a >= 0 && a < JOINTS && b >= 0 && b < JOINTS)
    }
    assert.equal(LINE_VERTICES, 2 * 21 * 2)
  })

  test('mirrored image coordinates map naturally: right is right, up is up, nearer is nearer', () => {
    const centre = toScene([0.5, 0.5, 0])
    assert.deepEqual(centre.slice(0, 2), [0, 0])
    assert.ok(toScene([0.9, 0.5, 0])[0] > 0)
    assert.ok(toScene([0.5, 0.1, 0])[1] > 0)
    assert.ok(toScene([0.5, 0.5, -0.1])[2] > centre[2])
    // In front of the entity's rings (radius ~1), so hands never pass behind the core.
    assert.ok(centre[2] > 1)
  })

  test('hands are written to stable slots, brighter when engaged, cleared when gone', () => {
    const buffers = createHandBuffers()
    writeHand(buffers, slotOf('Left'), hand({ side: 'Left', engaged: false }), 1)
    writeHand(buffers, slotOf('Right'), hand(), 1)
    const perHand = HAND_CONNECTIONS.length * 2
    assert.ok(buffers.lineGlow[0] > buffers.lineGlow[perHand], 'engaged right hand shines brighter')
    const wrist = toScene(hand().points[0])
    assert.deepEqual(Array.from(buffers.jointPositions.slice(0, 3)), wrist.map(Math.fround))

    writeHand(buffers, 0, null, 0)
    assert.ok(buffers.lineGlow.slice(0, perHand).every((v) => v === 0))
    assert.ok(buffers.lineGlow[perHand] > 0, 'the other hand is untouched')
  })

  test('thumb and index tips flare as they pinch', () => {
    assert.equal(pinchGlow(0.9), 0)
    assert.equal(pinchGlow(0.1), 1)
    const open = createHandBuffers()
    const pinched = createHandBuffers()
    writeHand(open, 0, hand({ pinch: 0.9 }), 1)
    writeHand(pinched, 0, hand({ pinch: 0.1 }), 1)
    assert.ok(pinched.jointGlow[8 * 2] > open.jointGlow[8 * 2])
    assert.equal(pinched.jointGlow[12 * 2], open.jointGlow[12 * 2], 'other fingertips do not flare')
  })
})
