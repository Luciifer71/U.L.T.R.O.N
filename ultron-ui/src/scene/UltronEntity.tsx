import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import type { Group } from 'three/webgpu'
import { liveSignals } from '../entity/liveSignals'
import { syncEntityUniforms } from '../entity/entityUniforms'
import ParticleCore from '../entity/ParticleCore'
import GyroRings from '../entity/GyroRings'
import ArcCage from '../entity/ArcCage'
import NeuralShell from '../entity/NeuralShell'
import Dust from '../entity/Dust'
import DataStream from '../entity/DataStream'
import Lightning from '../entity/Lightning'
import EntityGlow from '../entity/EntityGlow'

/* =========================================================
   ULTRON ENTITY
   The computational entity, from the inside out:
     particle core  → dense nucleus of independent orbits
     gyroscope rings → segmented luminous rings, each on its own axis
     arc cage       → many short spinning arcs forming a gyroscopic sphere
     neural shell   → nodes and links with travelling pulses
     dust           → faint sparks for depth
     data stream    → words flowing in to the core and replies flowing out
     lightning      → electric arcs while thinking or while the model works
   all inside Gaze, which turns toward the viewer when camera presence is on,
   plus a bloom + lens pass (light bending, colour split, streaks,
   glitches, hologram scan, vignette, grain) for the filmed look.
   ========================================================= */

function UniformSync() {
  // Runs before the layers read the shared clock (lower priority first).
  useFrame((_, delta) => {
    syncEntityUniforms(Math.min(delta, 0.05))
  }, -1)
  return null
}

/** Slowly turns the whole entity toward the viewer when camera presence is on. */
function Gaze({ children }: { children: React.ReactNode }) {
  const group = useRef<Group | null>(null)
  useFrame(() => {
    const { gazeX, gazeY, presence } = liveSignals.state
    if (!group.current) return
    group.current.rotation.y = gazeX * 0.4 * presence
    group.current.rotation.x = -gazeY * 0.28 * presence
  })
  return <group ref={group}>{children}</group>
}

export default function UltronEntity() {
  return (
    <>
      <UniformSync />
      <Gaze>
        <ParticleCore />
        <GyroRings />
        <ArcCage />
        <NeuralShell />
        <Dust />
        <DataStream />
        <Lightning />
      </Gaze>
      <EntityGlow />
    </>
  )
}
