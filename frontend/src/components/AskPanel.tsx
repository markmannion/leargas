import { useMemo, useState, type ReactNode } from 'react'
import type { DatasetQuestion, Drawing } from '../types'
import { TYPE_LABEL, guessLang } from '../format'
import { useVoiceInput } from '../voice'

interface Props {
  drawing: Drawing | null
  busy: boolean
  onAsk: (question: string, spoken?: boolean) => void
  voice: boolean
  children?: ReactNode
}

export function AskPanel({ drawing, busy, onAsk, voice, children }: Props) {
  const [text, setText] = useState('')
  const [lang, setLang] = useState<string>('all')

  const questions = useMemo(() => {
    const qs = (drawing?.questions ?? []).map((q) => ({ ...q, lang: guessLang(q.question) }))
    return qs
  }, [drawing])
  const langs = useMemo(() => [...new Set(questions.map((q) => q.lang))].sort(), [questions])
  const shown = lang === 'all' ? questions : questions.filter((q) => q.lang === lang)

  const submit = (q: string, spoken = false) => {
    const t = q.trim()
    if (!t || !drawing || busy) return
    setText(t)
    onAsk(t, spoken)
  }
  const mic = useVoiceInput((t) => submit(t, true))
  const micLabel =
    mic.state === 'recording' ? 'Stop recording' : mic.state === 'transcribing' ? 'Transcribing…' : 'Ask by voice'

  return (
    <section className="ask">
      <form
        className="ask-form"
        onSubmit={(e) => {
          e.preventDefault()
          submit(text)
        }}
      >
        <label htmlFor="question" className="field-label">
          Question
        </label>
        <textarea
          id="question"
          rows={3}
          value={text}
          placeholder={drawing ? 'How many windows are on this floor?' : 'Select a drawing first'}
          disabled={!drawing}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit(text)
            }
          }}
        />
        <div className="ask-actions">
          <span className="muted small">
            {mic.error ? (
              <span className="mic-error">{mic.error}</span>
            ) : mic.state === 'recording' ? (
              'Listening… click the mic again to ask.'
            ) : mic.state === 'transcribing' ? (
              'Transcribing…'
            ) : (
              'Any language. Enter to ask, Shift+Enter for a new line.'
            )}
          </span>
          {voice && (
            <button
              type="button"
              className={`mic mic-${mic.state}`}
              onClick={mic.toggle}
              disabled={!drawing || busy || mic.state === 'transcribing'}
              aria-label={micLabel}
              aria-pressed={mic.state === 'recording'}
              title={micLabel}
            >
              {mic.state === 'recording' ? <StopIcon /> : <MicIcon />}
            </button>
          )}
          <button type="submit" className="primary" disabled={!drawing || busy || !text.trim()}>
            {busy ? 'Asking…' : 'Ask'}
          </button>
        </div>
      </form>

      {children}

      {questions.length > 0 && (
        <div className="block">
          <div className="block-title-row">
            <h3 className="block-title">
              From the dataset <span className="mono muted">{shown.length}</span>
            </h3>
            {langs.length > 1 && (
              <div className="seg small" role="group" aria-label="Filter by language">
                {['all', ...langs].map((l) => (
                  <button key={l} className={lang === l ? 'on' : undefined} onClick={() => setLang(l)}>
                    {l === 'all' ? 'All' : l}
                  </button>
                ))}
              </div>
            )}
          </div>
          <ul className="question-list">
            {shown.map((q: DatasetQuestion & { lang: string }, i) => (
              <li key={i}>
                <button type="button" onClick={() => submit(q.question)} disabled={busy}>
                  <span className="q-text">{q.question}</span>
                  <span className="q-tags mono">
                    {q.lang} · {TYPE_LABEL[q.type]}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function MicIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <rect x="5" y="5" width="14" height="14" rx="3" />
    </svg>
  )
}
