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

          // Temporary diagnostic visibility.
          // We will disable this after the bridge is verified.
          debug: true,
        })

        if (disposed) {
          await connection.close()
          return
        }

        console.info(
          `[ULTRON BUS] Connected to ${NATS_WS_URL}`,
        )

        console.info(
          '[ULTRON BUS] Server:',
          connection.getServer(),
        )

        const subscription =
          connection.subscribe(
            ULTRON_VISUAL_SUBJECT,
          )

        console.info(
          `[ULTRON BUS] Subscribed to ${ULTRON_VISUAL_SUBJECT}`,
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

            console.debug(
              '[ULTRON BUS] Applied visual event',
              event,
            )
          } catch (error) {
            console.error(
              '[ULTRON BUS] Failed to process visual event',
              error,
            )
          }
        }

        console.info(
          '[ULTRON BUS] Subscription loop ended',
        )

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