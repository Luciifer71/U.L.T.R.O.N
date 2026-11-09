import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { createMood, NO_EVENT, SHAPES, SHOCK_ON_ENTER, SHOCK_ON_FINISH, Spring } from '../src/entity/mood.ts'
import { RING_COUNT, RINGS } from '../src/entity/entityConfig.ts'

const FRAME = 1 / 60

/** Deterministic pseudo-random sequence so tests never flake. */
function seeded(seed = 1) {
  let s = seed
  return () => {
    s = (s * 16807) % 2147483647
    return (s - 1) / 2147483646
  }
}

function run(engine: ReturnType<typeof createMood>, mode: Parameters<typeof engine.update>[0], seconds: number) {
  for (let i = 0; i < Math.round(seconds * 60); i++) engine.update(mode, FRAME)
}

describe('Spring', () => {
  test('settles on its target with a single gentle overshoot', () => {
    const spring = new Spring(0, 5, 2)
    let peak = 0
    for (let i = 0; i < 600; i++) peak = Math.max(peak, spring.step(1, FRAME))
    assert.ok(Math.abs(spring.value - 1) < 0.01, `settled at ${spring.value}`)
    assert.ok(peak > 1.05 && peak < 1.4, `overshoot ${peak}`)
  })
})

describe('mood engine', () => {
  test('awakens from collapsed, overshoots, and settles to the idle shape', () => {
    const engine = createMood({ random: seeded() })
    assert.ok(engine.state.core < 0.5, 'starts collapsed')
    let peak = 0
    for (let i = 0; i < 300; i++) {
      engine.update('idle', FRAME)
      peak = Math.max(peak, engine.state.cage)
    }
    assert.ok(peak > 1.02, 'unfolds past its rest size')
    assert.ok(Math.abs(engine.state.core - SHAPES.idle.core) < 0.02)
    assert.ok(engine.state.shock.age < 5, 'the awakening released a shockwave')
  })

  test('every mode settles to its own shape', () => {
    for (const [mode, shape] of Object.entries(SHAPES)) {
      const engine = createMood({ random: seeded() })
      run(engine, mode as keyof typeof SHAPES, 8)
      for (const key of ['core', 'cage', 'shell', 'align', 'spin', 'flow'] as const) {
        assert.ok(Math.abs(engine.state[key] - shape[key]) < 0.03, `${mode}.${key} = ${engine.state[key]}, want ${shape[key]}`)
      }
    }
  })

  test('executing locks the rings into one plane within about a second', () => {
    const engine = createMood({ random: seeded() })
    run(engine, 'idle', 6)
    run(engine, 'executing', 1.2)
    assert.ok(engine.state.align > 0.8, `align ${engine.state.align}`)
    run(engine, 'idle', 6)
    assert.ok(engine.state.align < 0.02, 'releases when the task ends')
  })

  test('shockwaves fire on the wake word, task start, alerts and task completion only', () => {
    const engine = createMood({ random: seeded() })
    run(engine, 'idle', 8)
    const quiet = engine.state.shock.age
    assert.ok(quiet > 5, 'no shock while nothing changes')

    for (const mode of Object.keys(SHOCK_ON_ENTER) as (keyof typeof SHOCK_ON_ENTER)[]) {
      run(engine, 'idle', 6)
      engine.update(mode, FRAME)
      assert.ok(engine.state.shock.age < 0.1, `${mode} should release a wave`)
      assert.equal(engine.state.shock.strength, SHOCK_ON_ENTER[mode])
    }

    run(engine, 'thinking', 3)
    assert.ok(engine.state.shock.age > 2.5, 'entering thinking is silent')
    engine.update('idle', FRAME)
    assert.equal(engine.state.shock.strength, SHOCK_ON_FINISH)
  })

  test('a shockwave makes the rings wobble a few degrees and settle within seconds', () => {
    const engine = createMood({ random: seeded(7) })
    run(engine, 'idle', 8)
    let peak = 0
    let late = 0
    for (let i = 0; i < 360; i++) {
      engine.update('listening', FRAME)
      const now = Math.max(...engine.state.ringWobble.flat().map(Math.abs))
      if (i < 120) peak = Math.max(peak, now)
      else if (i >= 240) late = Math.max(late, now) // 4-6 s later
    }
    const degrees = (peak * 180) / Math.PI
    assert.ok(degrees > 1 && degrees < 15, `peak wobble ${degrees.toFixed(1)} degrees`)
    // Idle thoughts may add a small twitch, but the shock's wobble has decayed.
    assert.ok(late < peak * 0.4, `late wobble ${late} vs peak ${peak}`)
  })

  test('idle thoughts are occasional: a few per half-minute, more while thinking', () => {
    const count = (mode: 'idle' | 'thinking' | 'sleep') => {
      const engine = createMood({ random: seeded(3) })
      let thoughts = 0
      let lastAge = engine.state.thought.age
      for (let i = 0; i < 30 * 60; i++) {
        engine.update(mode, FRAME)
        if (engine.state.thought.age < lastAge) thoughts++
        lastAge = engine.state.thought.age
      }
      return thoughts
    }
    const idle = count('idle')
    assert.ok(idle >= 3 && idle <= 9, `idle thoughts ${idle}`)
    assert.ok(count('thinking') > idle, 'thinking is busier')
    assert.ok(count('sleep') <= 1, 'sleep is almost still')
  })

  test('reduced motion keeps the behaviour but softens and slows it', () => {
    const full = createMood({ random: seeded(5) })
    const reduced = createMood({ random: seeded(5), reducedMotion: true })
    run(full, 'idle', 3)
    run(reduced, 'idle', 3)
    assert.ok(reduced.state.shock.strength < full.state.shock.strength)
    assert.ok(Math.abs(reduced.state.core - full.state.core) < 0.02, 'shape changes are unaffected')
  })

  test('ring spin follows the mood and each ring keeps its own speed', () => {
    const engine = createMood({ random: seeded() })
    run(engine, 'idle', 6)
    const speeds = RINGS.map((ring) => ring.spin)
    const before = [...engine.state.ringAngle]
    engine.spinRings(speeds, 1)
    engine.state.ringAngle.forEach((angle, i) => {
      assert.ok(Math.abs(angle - before[i] - speeds[i] * engine.state.spin) < 1e-9)
    })
  })

  test('event ages stay finite so GPU maths never sees Infinity', () => {
    const engine = createMood({ random: seeded() })
    assert.equal(engine.state.shock.age, NO_EVENT)
    assert.ok(Number.isFinite(engine.state.thought.age))
  })

  test('ring config and engine agree on the ring count', () => {
    assert.equal(createMood().state.ringWobble.length, RING_COUNT)
    assert.equal(RINGS.length, RING_COUNT)
  })
})
