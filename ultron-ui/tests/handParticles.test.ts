import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import {
  buildHandParticles, HAND_CONNECTIONS, JOINTS, KIND, MAX_HANDS, PALM_TRIANGLES, pinchGlow, slotOf, toScene, writeJoints,
} from '../src/entity/handParticles.ts'
import type { TrackedHand } from '../src/entity/liveSignals.ts'

function seeded(seed = 7) {
  let s = seed
  return () => {
    s = (s * 16807) % 2147483647
    return (s - 1) / 2147483646
  }
}

describe('particle hands', () => {
  test('bones and palm use valid MediaPipe landmark indices', () => {
    assert.equal(HAND_CONNECTIONS.length, 21)
    for (const pair of [...HAND_CONNECTIONS, ...PALM_TRIANGLES]) {
      for (const j of pair) assert.ok(j >= 0 && j < JOINTS)
    }
  })

  test('every particle belongs to one hand and points at that hand\'s joints', () => {
    const p = buildHandParticles(300, seeded())
    assert.equal(p.count, 300 * MAX_HANDS)
    for (let i = 0; i < p.count; i++) {
      const hand = i < 300 ? 0 : 1
      for (let k = 0; k < 3; k++) {
        const joint = p.joints[i * 4 + k]
        assert.ok(joint >= hand * JOINTS && joint < (hand + 1) * JOINTS, `particle ${i}`)
      }
      assert.ok(Object.values(KIND).includes(p.joints[i * 4 + 3] as 0 | 1 | 2))
    }
  })

  test('the mix is mostly flowing bones, some palm and bright tips', () => {
    const p = buildHandParticles(1000, seeded())
    const counts = [0, 0, 0]
    for (let i = 0; i < 1000; i++) counts[p.joints[i * 4 + 3]]++
    assert.ok(counts[KIND.bone] > counts[KIND.palm] && counts[KIND.palm] > counts[KIND.tip])
    assert.ok(counts[KIND.tip] > 50)
  })

  test('palm particles sit inside their triangle (weights sum to one)', () => {
    const p = buildHandParticles(500, seeded())
    for (let i = 0; i < p.count; i++) {
      if (p.joints[i * 4 + 3] !== KIND.palm) continue
      const [u, v, w] = p.weights.slice(i * 4, i * 4 + 3)
      assert.ok(u >= 0 && v >= 0 && w >= 0)
      assert.ok(Math.abs(u + v + w - 1) < 1e-5)
    }
  })

  test('mirrored image coordinates map naturally: right is right, up is up, nearer is nearer', () => {
    const centre = toScene([0.5, 0.5, 0])
    assert.deepEqual(centre.slice(0, 2), [0, 0])
    assert.ok(toScene([0.9, 0.5, 0])[0] > 0)
    assert.ok(toScene([0.5, 0.1, 0])[1] > 0)
    assert.ok(toScene([0.5, 0.5, -0.1])[2] > centre[2])
    assert.ok(centre[2] > 1, 'in front of the rings, never behind the core')
  })

  test('joints of each hand land in that hand\'s slot', () => {
    const hand: TrackedHand = {
      side: 'Left', pose: 'point', engaged: true, pinch: 0.9,
      points: Array.from({ length: 21 }, (_, i) => [0.3 + i * 0.01, 0.6, 0] as [number, number, number]),
    }
    const target = new Float32Array(MAX_HANDS * JOINTS * 3)
    writeJoints(target, slotOf('Left'), hand)
    assert.ok(target.slice(0, JOINTS * 3).every((v) => v === 0), 'the right-hand slot is untouched')
    assert.deepEqual(Array.from(target.slice(JOINTS * 3, JOINTS * 3 + 3)), toScene(hand.points[0]).map(Math.fround))
  })

  test('a pinch lights up only as the tips come together', () => {
    assert.equal(pinchGlow(0.9), 0)
    assert.ok(pinchGlow(0.28) > 0.85, 'touching (2.5 cm on a 9 cm palm)')
    assert.equal(pinchGlow(0.1), 1)
  })
})
