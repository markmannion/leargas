import { useState } from 'react'
import type { Answer, DatasetQuestion } from '../types'
import {
  SOURCE_LABEL,
  STATUS_LABEL,
  STATUS_NOTE,
  TYPE_LABEL,
  formatValue,
  matchesReference,
} from '../format'
import { sourceClass } from './SheetViewer'
import { SlabBreakdown } from './SlabBreakdown'
import { OpeningInventory } from './OpeningInventory'

interface Props {
  answer: Answer
  reference: DatasetQuestion | null
  hovered: number | null
  onHover: (i: number | null) => void
  /** Present when voice is on: replays / stops the spoken answer. */
  speech?: { speaking: boolean; onToggle: () => void; error: string | null }
}

export function AnswerCard({ answer, reference, hovered, onHover, speech }: Props) {
  const [focusedRoom, setFocusedRoom] = useState<{ answer: Answer; id: string } | null>(null)
  const roomAreas = answer.room_areas ?? []
  const cv = answer.status === 'cannot_verify'
  const rejectedGuess = cv && answer.sources.some((s) => s.answer !== null)
  const modelScore = answer.source === 'gemma_ft' || answer.source === 'gemma_base'
  const match = reference ? matchesReference(answer.answer, answer.unit, reference) : null
  const pct = Math.round(answer.confidence * 100)
  // Free-text answers can be a sentence; the big numeric style would fill the panel.
  const longText = typeof answer.answer === 'string' && answer.answer.length > 12

  return (
    <section className={`answer status-${answer.status}`} aria-live="polite">
      <header className="answer-head">
        <span className={`status-pill status-${answer.status}`}>{STATUS_LABEL[answer.status]}</span>
        <span className="answer-head-right">
          <span className="answer-meta mono">
            {TYPE_LABEL[answer.type]}
            {answer.latency_ms != null && <> · {formatMs(answer.latency_ms)}</>}
          </span>
          {speech && (
            <button
              type="button"
              className={`speak${speech.speaking ? ' on' : ''}`}
              onClick={speech.onToggle}
              aria-label={speech.speaking ? 'Stop reading the answer' : 'Read the answer aloud'}
              title={speech.error ?? (speech.speaking ? 'Stop' : 'Read aloud')}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor" />
                {speech.speaking ? <path d="M17 9l4 6M21 9l-4 6" /> : <path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12" />}
              </svg>
            </button>
          )}
        </span>
      </header>

      <div className={`answer-value${cv ? ' is-empty' : ''}${longText ? ' is-text' : ''}`}>
        {cv ? (
          <>
            <span className="value-big">—</span>
            <span className="value-caption">No verified answer</span>
          </>
        ) : (
          <>
            <span className="value-big">{typeof answer.answer === 'number' && (roomAreas.length > 0 || (answer.slab_areas?.length ?? 0) > 0 || answer.area_mode === 'intersection')
              ? formatArea(answer.answer) : formatValue(answer.answer, answer.unit)}</span>
            {answer.type === 'count' && <span className="value-caption">items counted</span>}
          </>
        )}
      </div>

      <p className="status-note">
        {rejectedGuess ? 'The model made a guess, but its score was too low to accept.' : STATUS_NOTE[answer.status]}
      </p>

      <dl className="facts">
        {answer.region && <div><dt>Scope</dt><dd>Selected region</dd></div>}
        {answer.region && answer.type === 'area' && (
          <div><dt>Area measurement</dt><dd>{answer.area_mode === 'intersection' ? 'Exact selected area' : 'Complete rooms'}</dd></div>
        )}
        <div>
          <dt>Source</dt>
          <dd>
            <span className={`swatch ${sourceClass(answer.source)}`} />
            {SOURCE_LABEL[answer.source]}
          </dd>
        </div>
        <div>
          <dt>{modelScore ? 'Model score' : 'Confidence'}</dt>
          <dd className="confidence" title={modelScore ? 'A score from the model’s answer tokens; not a probability that the answer is correct.' : undefined}>
            <span className="bar">
              <span style={{ width: `${pct}%` }} />
            </span>
            <span className="mono">{pct}%</span>
          </dd>
        </div>
        {reference && (
          <div>
            <dt>Dataset answer</dt>
            <dd>
              <span className="mono">{formatValue(reference.answer, reference.unit)}</span>
              {match !== null && (
                <span className={`match ${match ? 'ok' : 'bad'}`}>{match ? 'matches' : 'differs'}</span>
              )}
            </dd>
          </div>
        )}
      </dl>

      {answer.explanation && <p className="explanation">{answer.explanation}</p>}

      <SlabBreakdown answer={answer} onHover={onHover} />
      <OpeningInventory answer={answer} hovered={hovered} onHover={onHover} />

      {roomAreas.length > 0 && (
        <div className="block room-breakdown">
          <h3 className="block-title">{answer.area_mode === 'intersection' ? 'Selected floor areas' : 'Floor areas by room'}</h3>
          <p className="scope-help">Choose a room to highlight it on the plan. Areas are in m².</p>
          <table className="room-areas">
            <thead><tr><th scope="col">Room</th><th scope="col">Area</th><th scope="col">Basis</th></tr></thead>
            <tbody>
              {roomAreas.map((room) => {
                const active = room.evidence_indices.some((index) => index === hovered)
                const pinned = focusedRoom?.answer === answer && focusedRoom.id === room.id
                const index = room.evidence_indices[0] ?? null
                return (
                  <tr key={room.id} className={active ? 'active' : undefined}
                    onPointerEnter={() => onHover(index)}
                    onPointerLeave={() => {
                      const selected = focusedRoom?.answer === answer ? roomAreas.find((item) => item.id === focusedRoom.id) : null
                      onHover(selected?.evidence_indices[0] ?? null)
                    }}>
                    <th scope="row">
                      <button type="button" disabled={index === null} aria-pressed={pinned}
                        title={index === null ? 'Room area is available; no aligned sheet outline is available.' : 'Highlight this room on the plan'}
                        onFocus={() => onHover(index)}
                        onBlur={() => { if (!pinned) onHover(null) }}
                        onClick={() => { setFocusedRoom(pinned ? null : { answer, id: room.id }); onHover(pinned ? null : index) }}>
                        {room.room_id && <span className="mono">{room.room_id} </span>}{room.label}
                      </button>
                      {room.level && <small>{room.level}</small>}
                      {!room.complete && <small className="selected-portion">Selected portion</small>}
                    </th>
                    <td className="mono num" title={`${room.value} m²`}>{formatArea(room.value)}</td>
                    <td>{room.method === 'printed' ? 'Printed' : room.method === 'quantity' ? 'Model quantity' : 'CAD geometry'}</td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot><tr><th scope="row">Total</th><td className="mono num">{typeof answer.answer === 'number' ? formatArea(answer.answer) : '—'}</td><td /></tr></tfoot>
          </table>
          <p className="scope-help">Total calculated before rounding individual rooms.</p>
        </div>
      )}

      {answer.sources.length > 0 && (
        <div className="block">
          <h3 className="block-title">{rejectedGuess ? 'Unverified guesses' : 'Engines'}</h3>
          <table className="sources">
            <tbody>
              {answer.sources.map((s, i) => (
                <tr key={i} className={s.source === answer.source ? 'chosen' : undefined}>
                  <td>
                    <span className={`swatch ${sourceClass(s.source)}`} />
                    {SOURCE_LABEL[s.source]}
                  </td>
                  <td className="mono num">{formatValue(s.answer, s.unit)}</td>
                  <td className="mono num muted">{Math.round(s.confidence * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {answer.evidence.length > 0 && roomAreas.length === 0 && !answer.openings?.length && (
        <div className="block">
          <h3 className="block-title">
            Evidence <span className="mono muted">{answer.evidence.length}</span>
          </h3>
          <ol className="evidence-list">
            {answer.evidence.map((e, i) => (
              <li
                key={i}
                className={hovered === i ? 'active' : undefined}
                onPointerEnter={() => onHover(i)}
                onPointerLeave={() => onHover(null)}
              >
                <span className="ev-index mono">{i + 1}</span>
                <span className="ev-label">{e.label ?? e.shape.kind}</span>
                {e.value != null && <span className="mono num">{formatValue(e.value, answer.unit)}</span>}
                {e.page > 0 && <span className="mono muted">p{e.page + 1}</span>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  )
}

function formatMs(ms: number) {
  return ms < 1000 ? `${Math.max(1, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`
}

function formatArea(value: number) {
  return `${value.toFixed(2)} m²`
}
