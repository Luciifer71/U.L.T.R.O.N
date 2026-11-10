import assert from 'node:assert/strict'
import { test } from 'node:test'
import { randomOrbitBasis, RINGS } from '../src/entity/entityConfig.ts'

const dot = (a: number[], b: number[]) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

test('orbit bases are orthonormal for many random draws', () => {
  for (let i = 0; i < 2000; i++) {
    const { u, w } = randomOrbitBasis()
    assert.ok(Math.abs(dot(u, u) - 1) < 1e-9)
    assert.ok(Math.abs(dot(w, w) - 1) < 1e-9)
    assert.ok(Math.abs(dot(u, w)) < 1e-9)
  }
})

test('ring specs are sane', () => {
  for (const ring of RINGS) {
    assert.ok(ring.radius > 0.5 && ring.radius < 2, 'inside the frame')
    assert.ok(ring.duty > 0 && ring.duty <= 1)
    assert.ok(Number.isInteger(ring.count) && ring.count >= 0)
    assert.ok(ring.width > 0 && ring.width < ring.radius)
  }
})

test('frame-rate cap defaults to 60 and accepts only sensible overrides', async () => {
  const { parseMaxFps } = await import('../src/entity/entityConfig.ts')
  assert.equal(parseMaxFps(''), 60)
  assert.equal(parseMaxFps('?fps=30'), 30)
  assert.equal(parseMaxFps('?fps=144'), 144)
  for (const bad of ['?fps=5', '?fps=1000', '?fps=abc', '?fps=']) assert.equal(parseMaxFps(bad), 60, bad)
})
