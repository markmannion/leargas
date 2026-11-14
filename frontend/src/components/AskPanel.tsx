import { useMemo, useState, type ReactNode } from 'react'
import type { AreaMode, DatasetQuestion, Drawing, Region } from '../types'
import { TYPE_LABEL, guessLang } from '../format'
import { useVoiceInput } from '../voice'

interface Props {
  drawing: Drawing | null
  busy: boolean
  onAsk: (question: string, spoken?: boolean) => void
  voice: boolean
  region: Region | null
  selectingRegion: boolean
  onSelectRegion: () => void
  onClearRegion: () => void
  areaMode: AreaMode
  onAreaMode: (mode: AreaMode) => void
  onMeasureAreas: () => void
  children?: ReactNode
}

// Starters for an uploaded drawing, which has no dataset questions. They match parser templates /
// English rules, so geometry engines can take them when the upload has a DXF or IFC twin.
const STARTERS = [
  'How many doors are drawn on this floor plan?',
  'How many windows are drawn on this floor plan?',
  'How many rooms are there?',
  'How many bathrooms are there?',
  'What is the total floor area in m²?',
]

export function AskPanel({ drawing, busy, onAsk, voice, region, selectingRegion, onSelectRegion, onClearRegion, areaMode, onAreaMode, onMeasureAreas, children }: Props) {
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
    if (!t || !drawing || busy || selectingRegion) return
    setText(t)
    onAsk(t, spoken)
  }
  const mic = useVoiceInput((t) => submit(t, true))
  const micLabel =
    mic.state === 'recording' ? 'Stop recording' : mic.state === 'transcribing' ? 'Transcribing…' : 'Ask by voice'

  return (
    <section className="ask">
      <div className={`question-scope${region ? ' is-scoped' : ''}`}>
        <div className="scope-heading">
          <span className="field-label">Ask about</span>
          <strong>{region ? 'Selected region' : 'Whole plan'}</strong>
        </div>
        <div className="scope-actions">
          <button type="button" className={selectingRegion ? 'active' : ''} disabled={!drawing}
            aria-pressed={selectingRegion} onClick={onSelectRegion}>
            {selectingRegion ? 'Cancel selection' : region ? 'Redraw region' : 'Draw a region'}
          </button>
          {region && <button type="button" onClick={onClearRegion}>Use whole plan</button>}
        </div>
        <p className="scope-help" role="status">
          {selectingRegion
            ? 'Drag a box on the drawing. Escape cancels.'
            : region
              ? 'Only this region is checked. Counts include objects whose centers are inside the box.'
              : 'Ask about the entire drawing, or draw a box to focus on one area.'}
        </p>
      </div>
      <div className="floor-area-tools">
        <span className="field-label">Floor areas</span>
        {region && (
          <fieldset className="area-mode">
            <legend className="sr-only">How to measure floor area in the selection</legend>
            <label><input type="radio" name="area-mode" value="whole_rooms" checked={areaMode === 'whole_rooms'}
              onChange={() => onAreaMode('whole_rooms')} /> Complete rooms</label>
            <label><input type="radio" name="area-mode" value="intersection" checked={areaMode === 'intersection'}
              onChange={() => onAreaMode('intersection')} /> Exact selected area</label>
          </fieldset>
        )}
        <p className="scope-help">
          {!region
            ? 'See the total and a breakdown by room, with each room marked on the plan.'
            : areaMode === 'whole_rooms'
              ? 'Sum complete rooms using printed areas or CAD geometry. If the box cuts a room, redraw it or choose Exact selected area.'
              : 'Measure room floor polygons inside the box, including cut rooms and excluding voids. Requires aligned CAD geometry with known units.'}
        </p>
        <button type="button" className="measure-areas" disabled={!drawing || busy || selectingRegion}
          onClick={() => { setText('Show floor areas by room'); onMeasureAreas() }}>
          {region && areaMode === 'intersection' ? 'Measure selected floor area' : 'Show floor areas by room'}
        </button>
      </div>
      <div className="floor-area-tools">
        <span className="field-label">Slab specifications</span>
        <p className="scope-help">Group measured slab areas by type: thickness and bars. Missing specifications keep their area.
          {' '}IFC totals cover the model; ask for a named level to narrow them.
          {region && ' Use the whole plan for slab specifications.'}</p>
        <button type="button" className="measure-areas" disabled={!drawing || busy || selectingRegion || !!region}
          onClick={() => submit('Slab area by type (thickness and bars)')}>
          Show slab area by type
        </button>
      </div>
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
          placeholder={drawing ? region ? 'How many windows are in this region?' : 'How many windows are on this floor?' : 'Select a drawing first'}
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
              disabled={!drawing || busy || selectingRegion || mic.state === 'transcribing'}
              aria-label={micLabel}
              aria-pressed={mic.state === 'recording'}
              title={micLabel}
            >
              {mic.state === 'recording' ? <StopIcon /> : <MicIcon />}
            </button>
          )}
          <button type="submit" className="primary" disabled={!drawing || busy || selectingRegion || !text.trim()}>
            {busy ? 'Asking…' : 'Ask'}
          </button>
        </div>
      </form>

      {children}

      {drawing && drawing.questions.length === 0 && (
        <div className="block">
          <div className="block-title-row">
            <h3 className="block-title">Try asking</h3>
          </div>
          <ul className="question-list">
            {STARTERS.map((q) => (
              <li key={q}>
                <button type="button" onClick={() => submit(q)} disabled={busy}>
                  <span className="q-text">{q}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

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
                <button type="button" onClick={() => submit(q.question)} disabled={busy || selectingRegion}>
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
