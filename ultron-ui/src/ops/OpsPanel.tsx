import { useEffect, useRef, useState, type FormEvent } from 'react'
import './ops.css'
import { useOps, type Link, type OpsSnapshot, type TranscriptEntry, type VisionState } from './useOps'

const STORAGE_KEY = 'ultron.ops.open'

const LINK_TEXT: Record<Link, string> = {
  connecting: 'Connecting…',
  offline: 'Bus offline',
  'no-brain': 'Brain not answering',
  online: 'Online',
}

const COMPONENT_NAMES: Record<string, string> = {
  brain: 'Brain',
  listener: 'Listener',
  action_daemon: 'Action daemon',
  vision: 'Vision',
}

const SERVICE_NAMES: Record<string, string> = {
  ollama: 'Ollama',
  spotify: 'Spotify',
  google: 'Google',
}

function readOpen() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== '0'
  } catch {
    return true
  }
}

function ago(seconds: number | null | undefined, now: number) {
  if (!seconds) return 'never'
  const delta = Math.max(0, Math.round(now - seconds))
  if (delta < 5) return 'just now'
  if (delta < 60) return `${delta}s ago`
  return `${Math.round(delta / 60)}m ago`
}

function stepLabel(name: string) {
  // "open_resource:Calculator" -> "open resource · Calculator"
  const [kind, ...rest] = name.split(':')
  const target = rest.join(':')
  return target ? `${kind.replace(/_/g, ' ')} · ${target}` : kind.replace(/_/g, ' ')
}

function statusTone(status: string) {
  if (['completed', 'verified'].includes(status)) return 'good'
  if (['failed', 'preflight_failed'].includes(status)) return 'bad'
  if (['cancelled', 'not_started'].includes(status)) return 'muted'
  return 'busy'
}

function isTypingTarget(target: EventTarget | null) {
  const element = target as HTMLElement | null
  return !!element && (element.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(element.tagName))
}

export default function OpsPanel() {
  const [open, setOpen] = useState(readOpen)
  const { link, snapshot, transcript, notice, setNotice, sendCommand, stop, vision, toggleGesture } = useOps(true)

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, open ? '1' : '0')
    } catch {
      /* Remembering the panel state is optional. */
    }
  }, [open])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === '`' && !isTypingTarget(event.target)) setOpen((value) => !value)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 6000)
    return () => window.clearTimeout(timer)
  }, [notice, setNotice])

  if (!open) {
    return (
      <button className="ops-toggle" onClick={() => setOpen(true)} title="Open operations panel (`)">
        <span className={`ops-dot ops-dot--${link}`} /> Ops
      </button>
    )
  }

  return (
    <aside className="ops-panel" aria-label="Ultron operations">
      <header className="ops-header">
        <div className="ops-title">
          <span className={`ops-dot ops-dot--${link}`} />
          <span>Operations</span>
          <span className="ops-link">{LINK_TEXT[link]}</span>
        </div>
        <button className="ops-close" onClick={() => setOpen(false)} title="Hide panel (`)" aria-label="Hide panel">
          ×
        </button>
      </header>

      <button className="ops-stop" onClick={() => void stop()} disabled={link === 'offline'}>
        Stop
      </button>
      <p className="ops-hint">Stops speech, drops queued requests and stops the current task before its next step. A step already running finishes; nothing is undone.</p>
      {notice && <p className="ops-notice" role="status">{notice}</p>}

      <GestureToggle vision={vision} disabled={link === 'offline'} onToggle={() => void toggleGesture()} />

      <CurrentSection snapshot={snapshot} />
      <TranscriptSection transcript={transcript} />
      <CommandBox disabled={link === 'offline'} onSend={sendCommand} />
      <HealthSection snapshot={snapshot} link={link} />
      <RecentSection snapshot={snapshot} />
    </aside>
  )
}

function GestureToggle({ vision, disabled, onToggle }: { vision: VisionState | null; disabled: boolean; onToggle: () => void }) {
  const on = vision?.gesture === true
  const status = !vision ? 'Vision service not running' : on ? 'Camera on · tracking your hands' : 'Camera off'
  return (
    <div className="ops-gesture">
      <button
        className={`ops-gesture-button${on ? ' ops-gesture-button--on' : ''}`}
        onClick={onToggle}
        disabled={disabled}
        aria-pressed={on}
        title="Also: double clap, or say “Ultron, gesture mode”. Both palms for 1 s turns it off."
      >
        Gesture mode {on ? 'on' : 'off'}
      </button>
      <span className="ops-meta">{status}</span>
    </div>
  )
}

function CurrentSection({ snapshot }: { snapshot: OpsSnapshot | null }) {
  const current = snapshot?.current
  return (
    <section className="ops-section">
      <h2>Now</h2>
      {current ? (
        <div className="ops-current">
          <div className="ops-current-head">
            <span className={`ops-pill ops-pill--${current.stage === 'stopping' ? 'bad' : 'busy'}`}>{current.stage}</span>
            <span className="ops-current-prompt">“{current.prompt}”</span>
          </div>
          {current.steps.length > 0 && (
            <ol className="ops-steps">
              {current.steps.map((step, index) => (
                <li key={`${step.name}-${index}`}>
                  <span className={`ops-pill ops-pill--${statusTone(step.state)}`}>{step.state}</span>
                  <span>{stepLabel(step.name)}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      ) : (
        <p className="ops-empty">Idle{snapshot ? '' : ' (no status yet)'}</p>
      )}
      {!!snapshot?.queued && <p className="ops-meta">{snapshot.queued} request(s) waiting</p>}
    </section>
  )
}

function TranscriptSection({ transcript }: { transcript: TranscriptEntry[] }) {
  const end = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [transcript])
  return (
    <section className="ops-section">
      <h2>Transcript</h2>
      <div className="ops-transcript">
        {transcript.length === 0 && <p className="ops-empty">Requests and replies appear here.</p>}
        {transcript.map((entry) => (
          <div key={entry.id} className={`ops-line ops-line--${entry.role}`}>
            <span className="ops-line-who">
              {entry.role === 'you' ? (entry.fromDashboard ? 'You (typed)' : 'You') : 'Ultron'}
              {entry.role === 'ultron' && entry.cancelled && <span className="ops-tag">stopped</span>}
              {entry.role === 'ultron' && entry.ok === false && !entry.cancelled && <span className="ops-tag ops-tag--bad">failed</span>}
            </span>
            <span className="ops-line-text">{entry.text}</span>
          </div>
        ))}
        <div ref={end} />
      </div>
    </section>
  )
}

function CommandBox({ disabled, onSend }: { disabled: boolean; onSend: (text: string) => boolean }) {
  const [text, setText] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (onSend(text)) setText('')
  }
  return (
    <form className="ops-command" onSubmit={submit}>
      <input
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={disabled ? 'Not connected' : 'Type a request…'}
        maxLength={1000}
        disabled={disabled}
        aria-label="Type a request for Ultron"
      />
      <button type="submit" disabled={disabled || !text.trim()}>Send</button>
    </form>
  )
}

function HealthSection({ snapshot, link }: { snapshot: OpsSnapshot | null; link: Link }) {
  // Server time keeps "last seen" consistent with the heartbeat clock.
  const now = snapshot?.observedAt ?? 0
  const components = snapshot?.components ?? {}
  return (
    <section className="ops-section">
      <h2>Health</h2>
      <ul className="ops-health">
        {Object.keys(COMPONENT_NAMES).map((key) => {
          const item = components[key]
          const online = key === 'brain' ? link === 'online' : !!item?.online
          return (
            <li key={key}>
              <span className={`ops-dot ops-dot--${online ? 'online' : 'offline'}`} />
              <span>{COMPONENT_NAMES[key]}</span>
              <span className="ops-meta">{key === 'brain' ? LINK_TEXT[link] : online ? 'online' : `last seen ${ago(item?.lastSeen, now)}`}</span>
            </li>
          )
        })}
        {Object.entries(SERVICE_NAMES).map(([key, label]) => {
          const service = snapshot?.services?.[key]
          return (
            <li key={key}>
              <span className={`ops-dot ops-dot--${service ? (service.ok ? 'online' : 'warn') : 'connecting'}`} />
              <span>{label}</span>
              <span className="ops-meta" title={service?.detail}>{service ? service.detail : 'unknown'}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function RecentSection({ snapshot }: { snapshot: OpsSnapshot | null }) {
  const recent = snapshot?.recent ?? []
  return (
    <section className="ops-section">
      <h2>Recent tasks</h2>
      {recent.length === 0 ? (
        <p className="ops-empty">No recorded tasks yet.</p>
      ) : (
        <ul className="ops-recent">
          {recent.map((task) => (
            <li key={task.taskId} title={task.error ?? task.result}>
              <span className={`ops-pill ops-pill--${statusTone(task.status)}`}>{task.status}</span>
              <span className="ops-recent-prompt">{task.prompt}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
