import { useMemo, useState, type ReactNode } from 'react'
import type { DatasetQuestion, Drawing } from '../types'
import { TYPE_LABEL, guessLang } from '../format'

interface Props {
  drawing: Drawing | null
  busy: boolean
  onAsk: (question: string) => void
  children?: ReactNode
}

export function AskPanel({ drawing, busy, onAsk, children }: Props) {
  const [text, setText] = useState('')
  const [lang, setLang] = useState<string>('all')

  const questions = useMemo(() => {
    const qs = (drawing?.questions ?? []).map((q) => ({ ...q, lang: guessLang(q.question) }))
    return qs
  }, [drawing])
  const langs = useMemo(() => [...new Set(questions.map((q) => q.lang))].sort(), [questions])
  const shown = lang === 'all' ? questions : questions.filter((q) => q.lang === lang)

  const submit = (q: string) => {
    const t = q.trim()
    if (!t || !drawing || busy) return
    setText(t)
    onAsk(t)
  }

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
          <span className="muted small">Any language. Enter to ask, Shift+Enter for a new line.</span>
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
