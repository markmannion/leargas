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

interface Props {
  answer: Answer
  reference: DatasetQuestion | null
  hovered: number | null
  onHover: (i: number | null) => void
  /** Present when voice is on: replays / stops the spoken answer. */
  speech?: { speaking: boolean; onToggle: () => void; error: string | null }
}

export function AnswerCard({ answer, reference, hovered, onHover, speech }: Props) {
  const cv = answer.status === 'cannot_verify'
  const match = reference ? matchesReference(answer.answer, answer.unit, reference) : null
  const pct = Math.round(answer.confidence * 100)

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

      <div className={`answer-value${cv ? ' is-empty' : ''}`}>
        {cv ? (
          <>
            <span className="value-big">—</span>
            <span className="value-caption">No answer given</span>
          </>
        ) : (
          <>
            <span className="value-big">{formatValue(answer.answer, answer.unit)}</span>
            {answer.type === 'count' && <span className="value-caption">items counted</span>}
          </>
        )}
      </div>

      <p className="status-note">{STATUS_NOTE[answer.status]}</p>

      <dl className="facts">
        <div>
          <dt>Source</dt>
          <dd>
            <span className={`swatch ${sourceClass(answer.source)}`} />
            {SOURCE_LABEL[answer.source]}
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd className="confidence">
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

      {answer.sources.length > 0 && (
        <div className="block">
          <h3 className="block-title">Engines</h3>
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

      {answer.evidence.length > 0 && (
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
