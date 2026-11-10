import { useEffect } from 'react'
import {
  wsconnect,
  type NatsConnection,
} from '@nats-io/nats-core'

import {
  ULTRON_VISUAL_SUBJECT,
  parseUltronVisualEvent,
} from './ultronVisualEvent'

import {
  setUltronMode,
} from '../simulation/entitySimulation'

import { liveSignals } from '../entity/liveSignals'

// Live data the entity reacts to (see src/entity/liveSignals.ts).
const LIVE_SUBJECTS = [
  'ultron.signal.>',
  'ultron.status.speaking',
  'ultron.intent',
  'ultron.voice',
] as const

async function feedLiveSignals(
  connection: NatsConnection,
  subject: string,
  isDisposed: () => boolean,
) {
  for await (const message of connection.subscribe(subject)) {
    if (isDisposed()) break
    try {
      liveSignals.handle(message.subject, JSON.parse(message.string()), performance.now() / 1000)
    } catch {
      // Malformed messages are ignored; they only ever drive visuals.
    }
  }
}

const NATS_WS_URL =
  import.meta.env.VITE_ULTRON_NATS_WS_URL ??
  'ws://127.0.0.1:9222'

const CLIENT_NAME = 'ultron-visual-bridge'

export function UltronEventBridge() {
  useEffect(() => {
    let connection: NatsConnection | null = null
    let disposed = false

    const connectToUltronBus = async () => {
      console.info(
        `[ULTRON BUS] Connecting to ${NATS_WS_URL}`,
      )

      try {
        connection = await wsconnect({
          servers: [NATS_WS_URL],

          name: CLIENT_NAME,

          // Reconnect automatically after temporary transport loss.
          reconnect: true,
          maxReconnectAttempts: -1,
          reconnectTimeWait: 2000,
          reconnectJitter: 250,

          // Don't give up before the initial NATS handshake completes.
          waitOnFirstConnect: true,
          timeout: 10000,

          // The browser must remain on the explicitly configured
          // WebSocket endpoint rather than discovering cluster
          // endpoints that may not be browser-accessible.
          ignoreClusterUpdates: true,

        })

        if (disposed) {
          await connection.close()
          return
        }

        console.info(
          `[ULTRON BUS] Connected to ${NATS_WS_URL}`,
        )

        for (const subject of LIVE_SUBJECTS) {
          void feedLiveSignals(connection, subject, () => disposed)
        }

        const subscription =
          connection.subscribe(
            ULTRON_VISUAL_SUBJECT,
          )

        for await (const message of subscription) {
          if (disposed) {
            break
          }

          try {
            const payload = JSON.parse(
              message.string(),
            )

            const event =
              parseUltronVisualEvent(payload)

            if (!event) {
              console.warn(
                '[ULTRON BUS] Rejected invalid visual event',
                payload,
              )

              continue
            }

            setUltronMode(event.event)

          } catch (error) {
            console.error(
              '[ULTRON BUS] Failed to process visual event',
              error,
            )
          }
        }

      } catch (error) {
        if (!disposed) {
          console.error(
            '[ULTRON BUS] NATS connection failed',
            error,
          )
        }
      }
    }

    void connectToUltronBus()

    return () => {
      disposed = true

      if (connection) {
        void connection.drain().catch(() => {
          void connection?.close()
        })
      }
    }
  }, [])

  return null
}