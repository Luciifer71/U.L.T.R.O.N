import {
  DEFAULT_ULTRON_ENTITY_STATE,
  type UltronEntityState,
  type UltronMode,
} from '../state/entityState'

import {
  updateUltronVisualState,
} from '../state/visualStateRuntime'
/* =========================================================
   ENTITY SIMULATION
   Deterministic, continuously evolving semantic state.

   This is intentionally independent from React and Three.js.
   Later, real ULTRON Core events will drive the same system.
   ========================================================= */

const state: UltronEntityState = {
  ...DEFAULT_ULTRON_ENTITY_STATE,
}

const subscribers = new Set<
  (state: UltronEntityState) => void
>()

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

function approach(
  current: number,
  target: number,
  rate: number,
  dt: number,
): number {
  const amount =
    1 - Math.exp(-rate * dt)

  return current +
    (target - current) * amount
}

/* =========================================================
   MODE TARGETS
   ========================================================= */

function getModeTargets(mode: UltronMode) {

  switch (mode) {

    case 'starting':
      return {
        energy: 0.70,
        activity: 0.45,
        attention: 0.30,
        processing: 0.30,
        stability: 0.70,
        urgency: 0.10,
        interaction: 0.20,
      }

    case 'listening':
      return {
        energy: 0.65,
        activity: 0.42,
        attention: 0.90,
        processing: 0.25,
        stability: 0.85,
        urgency: 0.15,
        interaction: 0.85,
      }

    case 'thinking':
      return {
        energy: 0.82,
        activity: 0.82,
        attention: 0.88,
        processing: 0.92,
        stability: 0.72,
        urgency: 0.28,
        interaction: 0.55,
      }

    case 'executing':
      return {
        energy: 0.90,
        activity: 0.95,
        attention: 0.82,
        processing: 0.96,
        stability: 0.78,
        urgency: 0.45,
        interaction: 0.60,
      }

    case 'alert':
      return {
        energy: 0.95,
        activity: 0.92,
        attention: 1.00,
        processing: 0.85,
        stability: 0.55,
        urgency: 1.00,
        interaction: 0.70,
      }

    case 'focus':
      return {
        energy: 0.78,
        activity: 0.65,
        attention: 1.00,
        processing: 0.80,
        stability: 0.92,
        urgency: 0.18,
        interaction: 0.35,
      }

    case 'sleep':
      return {
        energy: 0.18,
        activity: 0.05,
        attention: 0.02,
        processing: 0.02,
        stability: 0.98,
        urgency: 0.00,
        interaction: 0.00,
      }

    case 'offline':
      return {
        energy: 0.02,
        activity: 0.00,
        attention: 0.00,
        processing: 0.00,
        stability: 1.00,
        urgency: 0.00,
        interaction: 0.00,
      }

    case 'idle':
    default:
      return {
        energy: 0.55,
        activity: 0.20,
        attention: 0.35,
        processing: 0.10,
        stability: 0.90,
        urgency: 0.05,
        interaction: 0.05,
      }
  }
}

/* =========================================================
   SIMULATION TICK
   ========================================================= */

export function updateEntitySimulation(
  dt: number,
): void {

  const t =
    state.simulationTime

  state.simulationTime += dt
  updateUltronVisualState(
  state.mode,
  dt,
)

  const targets =
    getModeTargets(state.mode)

  /*
   * Small continuous internal fluctuations.
   * These represent background computational activity,
   * not visual rotation.
   */

  const breathing =
    Math.sin(t * 0.65) * 0.035

  const computationalWave =
    Math.sin(t * 1.37 + 1.7) * 0.04

  const networkWave =
    0.5 +
    0.5 *
    Math.sin(t * 0.82 + 3.1)

  const memoryWave =
    0.5 +
    0.5 *
    Math.sin(t * 0.43 + 5.2)

  state.energy =
    approach(
      state.energy,
      clamp01(
        targets.energy +
        breathing
      ),
      2.5,
      dt,
    )

  state.activity =
    approach(
      state.activity,
      clamp01(
        targets.activity +
        computationalWave
      ),
      2.8,
      dt,
    )

  state.attention =
    approach(
      state.attention,
      clamp01(
        targets.attention +
        Math.sin(t * 0.91) * 0.025
      ),
      2.2,
      dt,
    )

  state.processing =
    approach(
      state.processing,
      clamp01(
        targets.processing +
        computationalWave * 0.8
      ),
      3.0,
      dt,
    )

  state.stability =
    approach(
      state.stability,
      clamp01(
        targets.stability -
        Math.abs(computationalWave) * 0.15
      ),
      1.6,
      dt,
    )

  state.urgency =
    approach(
      state.urgency,
      clamp01(
        targets.urgency +
        Math.max(0, computationalWave) * 0.15
      ),
      2.0,
      dt,
    )

  state.interaction =
    approach(
      state.interaction,
      clamp01(
        targets.interaction
      ),
      2.5,
      dt,
    )

  /*
   * Background subsystems.
   */

  state.networkActivity =
    approach(
      state.networkActivity,
      networkWave * state.activity,
      1.8,
      dt,
    )

  state.memoryActivity =
    approach(
      state.memoryActivity,
      memoryWave *
      (0.15 + state.attention * 0.45),
      1.4,
      dt,
    )

  state.taskActivity =
    approach(
      state.taskActivity,
      state.processing *
      (0.2 + state.activity * 0.8),
      2.2,
      dt,
    )

  for (
    const subscriber
    of subscribers
  ) {
    subscriber(state)
  }
}

/* =========================================================
   MODE CONTROL
   ========================================================= */

export function setUltronMode(
  mode: UltronMode,
): void {

  const previousMode = state.mode

  if (previousMode === mode) {
    return
  }

  state.mode = mode

  console.info(
    `[ULTRON STATE] ${previousMode} → ${mode}`,
  )
}

/* =========================================================
   STATE ACCESS
   ========================================================= */

export function getUltronEntityState():
  UltronEntityState {
  return state
}

export function subscribeToUltronEntity(
  listener: (
    state: UltronEntityState
  ) => void,
): () => void {

  subscribers.add(listener)

  return () => {
    subscribers.delete(listener)
  }
}