import { describe, test } from 'node:test'
import assert from 'node:assert/strict'
import {
  buildHandParticles, HAND_CONNECTIONS, JOINTS, KIND, MAX_HANDS, PALM_TRIANGLES, handView, mapHand, palmCentre, pinchGlow, PLANE_Z, slotOf, writeJoints,
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

  // A wide (16:9) screen: the hands' plane is 3.55 units from the camera, fov 50.
  const wide = handView(4.8, 50, 16 / 9)
  // A small open hand drawn around a palm centre (x, y) in the camera picture.
  const handAt = (x: number, y: number): [number, number, number][] =>
    Array.from({ length: 21 }, (_, i) => [x + ((i % 5) - 2) * 0.01, y + (Math.floor(i / 5) - 2) * 0.01, -i * 0.001])

  test('the view at the hands\' depth matches the camera', () => {
    assert.ok(Math.abs(wide.halfHeight - (4.8 - PLANE_Z) * Math.tan((25 * Math.PI) / 180)) < 1e-9)
    assert.ok(Math.abs(wide.halfWidth / wide.halfHeight - 16 / 9) < 1e-9)
  })

  test('a hand can reach the whole screen, not a box in the middle', () => {
    // Regression: hands were laid out in a fixed 4:3 box on a 16:9 screen.
    for (const [x, y] of [[0.02, 0.5], [0.98, 0.5], [0.5, 0.02], [0.5, 0.98]]) {
      const centre = palmCentre(mapHand(handAt(x, y), wide))
      const reachX = Math.abs(centre[0]) / wide.halfWidth
      const reachY = Math.abs(centre[1]) / wide.halfHeight
      assert.ok(Math.max(reachX, reachY) > 0.88, `palm at (${x}, ${y}) reaches the screen edge`)
      assert.ok(reachX <= 1 && reachY <= 1, 'but stays on screen')
    }
  })

  test('mirrored picture maps naturally: right is right, up is up, nearer is nearer', () => {
    assert.ok(palmCentre(mapHand(handAt(0.8, 0.5), wide))[0] > 0)
    assert.ok(palmCentre(mapHand(handAt(0.5, 0.2), wide))[1] > 0)
    const flat = handAt(0.5, 0.5)
    const near = flat.map((p, i) => (i === 8 ? [p[0], p[1], p[2] - 0.1] : p)) as [number, number, number][]
    assert.ok(mapHand(near, wide)[8][2] > mapHand(flat, wide)[8][2])
    assert.ok(mapHand(flat, wide)[0][2] > 1, 'in front of the rings, never behind the core')
  })

  test('hands keep their true shape on any screen and camera aspect', () => {
    // A square in camera pixels (16:9 picture) must stay square on screen.
    const aspect = 16 / 9
    const square: [number, number, number][] = Array.from({ length: 21 }, () => [0.5, 0.5, 0])
    square[1] = [0.5 + 0.1 / aspect, 0.5, 0] // 0.1 picture-heights to the right
    square[2] = [0.5, 0.5 + 0.1, 0] // 0.1 picture-heights down
    for (const view of [wide, handView(4.8, 50, 4 / 3), handView(4.8, 50, 21 / 9)]) {
      const m = mapHand(square, view, aspect)
      const across = Math.abs(m[1][0] - m[0][0])
      const down = Math.abs(m[2][1] - m[0][1])
      assert.ok(Math.abs(across - down) < 1e-9, 'not stretched')
    }
  })

  test('joints of each hand land in that hand\'s slot', () => {
    const hand: TrackedHand = { side: 'Left', pose: 'point', engaged: true, pinch: 0.9, points: handAt(0.3, 0.6) }
    const target = new Float32Array(MAX_HANDS * JOINTS * 3)
    writeJoints(target, slotOf('Left'), hand, wide)
    assert.ok(target.slice(0, JOINTS * 3).every((v) => v === 0), 'the right-hand slot is untouched')
    assert.deepEqual(Array.from(target.slice(JOINTS * 3, JOINTS * 3 + 3)), mapHand(hand.points, wide)[0].map(Math.fround))
  })

  test('a pinch lights up only as the tips come together', () => {
    assert.equal(pinchGlow(0.9), 0)
    assert.ok(pinchGlow(0.28) > 0.85, 'touching (2.5 cm on a 9 cm palm)')
    assert.equal(pinchGlow(0.1), 1)
  })
})
