import {
  useEffect,
} from 'react'

import {
  useFrame,
} from '@react-three/fiber'

import {
  setUltronMode,
  updateEntitySimulation,
} from './entitySimulation'

export default function SimulationRuntime() {

  useEffect(() => {

    const handleKeyDown =
      (event: KeyboardEvent) => {

        // Typing in the operations panel must not switch animation modes.
        const target = event.target as HTMLElement | null
        if (
          target &&
          (target.isContentEditable ||
            ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
        ) {
          return
        }

        let mode:
          | 'idle'
          | 'listening'
          | 'thinking'
          | 'executing'
          | 'alert'
          | 'focus'
          | 'sleep'
          | null = null

        switch (event.key) {

          case '1':
            mode = 'idle'
            break

          case '2':
            mode = 'listening'
            break

          case '3':
            mode = 'thinking'
            break

          case '4':
            mode = 'executing'
            break

          case '5':
            mode = 'alert'
            break

          case '6':
            mode = 'focus'
            break

          case '7':
            mode = 'sleep'
            break
        }

        if (!mode) {
          return
        }

        setUltronMode(mode)

        console.log(
          '[ULTRON MODE]',
          mode,
        )
      }

    window.addEventListener(
      'keydown',
      handleKeyDown,
    )

    console.log(
      '[ULTRON] Keyboard mode controller active',
    )

    return () => {

      window.removeEventListener(
        'keydown',
        handleKeyDown,
      )

    }

  }, [])

  useFrame(
    (_, delta) => {

      const dt =
        Math.min(
          delta,
          0.05,
        )

      updateEntitySimulation(
        dt,
      )
    },
  )

  return null
}