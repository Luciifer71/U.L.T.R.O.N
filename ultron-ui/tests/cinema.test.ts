import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createCinema, type CinemaInputs } from '../src/entity/cinema.ts'

const FRAME = 1 / 60
const calm: CinemaInputs = { mode: 'idle', model: 0, stepFailed: false }

function seeded(seed = 1) {
  let s = seed
  return () => {
    s = (s * 16807) % 2147483647
    return (s - 1) / 2147483646
  }
}

function run(cinema: ReturnType<typeof createCinema>, seconds: number, inputs: CinemaInputs = calm) {
  for (let i = 0; i < Math.round(seconds * 60); i++) cinema.update(FRAME, inputs)
}

test('a failed step glitches hard and briefly', () => {
  const cinema = createCinema(seeded())
  run(cinema, 1)
  cinema.update(FRAME, { ...calm, stepFailed: true })
  assert.ok(cinema.state.glitch > 0.8)
  run(cinema, 0.8)
  assert.ok(cinema.state.glitch < 0.01, 'gone within a second')
})

test('idle micro-glitches are rare: one or two a minute, never in sleep', () => {
  const count = (mode: CinemaInputs['mode']) => {
    const cinema = createCinema(seeded(4))
    let bursts = 0
    let previous = 0
    for (let i = 0; i < 120 * 60; i++) {
      cinema.update(FRAME, { ...calm, mode })
      if (cinema.state.glitch > previous + 0.1) bursts++
      previous = cinema.state.glitch
    }
    return bursts
  }
  const idle = count('idle')
  assert.ok(idle >= 2 && idle <= 6, `idle bursts in 2 minutes: ${idle}`)
  assert.equal(count('sleep'), 0)
})

test('entering alert glitches; staying in alert does not keep glitching', () => {
  const cinema = createCinema(seeded())
  run(cinema, 1)
  cinema.update(FRAME, { ...calm, mode: 'alert' })
  assert.ok(cinema.state.glitch > 0.7)
  run(cinema, 2, { ...calm, mode: 'alert' })
  assert.ok(cinema.state.glitch < 0.01)
})

test('the hologram scan sweeps top to bottom, then hides', () => {
  const cinema = createCinema(seeded())
  const seen: number[] = []
  for (let i = 0; i < 20 * 60; i++) {
    cinema.update(FRAME, calm)
    if (cinema.state.scan >= -0.15) seen.push(cinema.state.scan)
  }
  assert.ok(seen.length > 0, 'a scan happened within 20 s')
  assert.ok(seen[0] > 1 && Math.min(...seen) < 0, 'enters above the frame and leaves below')
  assert.equal(cinema.state.scan === -1 || cinema.state.scan >= -0.15, true)
})

test('lightning follows thinking and model work, and fades out', () => {
  const cinema = createCinema(seeded())
  run(cinema, 3)
  assert.ok(cinema.state.lightning < 0.01, 'calm when idle')
  run(cinema, 3, { ...calm, mode: 'thinking' })
  assert.ok(cinema.state.lightning > 0.55)
  run(cinema, 3, { ...calm, mode: 'idle', model: 1 })
  assert.ok(cinema.state.lightning > 0.5, 'the model working is enough')
  run(cinema, 4)
  assert.ok(cinema.state.lightning < 0.02)
})

test('reduced motion keeps every effect but much softer', () => {
  const soft = createCinema(seeded(), true)
  soft.update(FRAME, { ...calm, stepFailed: true })
  assert.ok(soft.state.glitch > 0 && soft.state.glitch < 0.35)
  run(soft, 3, { ...calm, mode: 'thinking' })
  assert.ok(soft.state.lightning > 0 && soft.state.lightning < 0.25)
})
