import type { Answer, Engine, Source, SourceAnswer } from '../../types'
import { formatValue } from '../../format'
import type { GemmaState } from '../../core/session'

// Two independent checks on every question: one measures the drawing's own data (CAD geometry,
// the IFC model, or the sheet's printed text and lines), the other is Gemma looking at the image.
// Each lane has one colour that is reused for its marks on the sheet.

type Lane = 'measure' | 'model'

const laneOf = (s: Source | null | undefined): Lane =>
  s === 'gemma_ft' || s === 'gemma_base' ? 'model' : 'measure'

const NAME: Record<Source, string> = {
  geometry_dxf: 'DXF geometry',
  geometry_ifc: 'IFC model',
  sheet_reader: 'Sheet reader',
  gemma_ft: 'Gemma, fine-tuned',
  gemma_base: 'Gemma, base',
  mock: 'Mock',
}

const HOW: Record<Source, string> = {
  geometry_dxf: 'Measures the CAD file',
  geometry_ifc: 'Measures the IFC model',
  sheet_reader: 'Reads the sheet’s text and lines',
  gemma_ft: 'Looks at the image',
  gemma_base: 'Looks at the image',
  mock: 'Mock',
}

interface Side {
  lane: Lane
  got: SourceAnswer | null
  why: string | null // why there is no answer from this side
}

function side(a: Answer, lane: Lane, engine: Engine, gemma: GemmaState | undefined): Side {
  const got = a.sources.find((s) => laneOf(s.source) === lane)
    ?? (laneOf(a.source) === lane && a.status !== 'cannot_verify'
      ? { source: a.source, answer: a.answer, unit: a.unit, confidence: a.confidence }
      : null)
  if (got) return { lane, got, why: null }
  let why: string
  if (lane === 'measure') {
    why = engine === 'gemma_ft' || engine === 'gemma_base' ? 'Switched off' : 'No CAD file or readable sheet text'
  } else if (engine === 'geometry' || engine === 'sheet') {
    why = 'Switched off'
  } else if (gemma && gemma !== 'available') {
    why = { unconfigured: 'Not connected', unavailable: 'Offline', checking: 'Still connecting', disabled: 'Disabled' }[gemma]
  } else {
    why = 'Not run on this question'
  }
  return { lane, got: null, why }
}

type Verdict = { kind: 'agree' | 'differ' | 'single' | 'none'; title: string; sub: string }

function verdict(a: Answer, m: Side, g: Side): Verdict {
  const both = m.got?.answer != null && g.got?.answer != null
  if (a.status === 'cannot_verify') {
    return { kind: 'none', title: 'Held back', sub: both ? 'Neither was sure enough' : 'Nothing sure enough' }
  }
  if (both) {
    if (a.status === 'disagreement') return { kind: 'differ', title: 'Disagree', sub: gap(m.got!, g.got!) }
    return { kind: 'agree', title: 'Agree', sub: 'Two checks, one answer' }
  }
  return { kind: 'single', title: 'One check', sub: 'Nothing to compare with' }
}

function gap(x: SourceAnswer, y: SourceAnswer): string {
  const a = Number(x.answer), b = Number(y.answer)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 'Different answers'
  const d = Math.abs(a - b)
  if (x.unit === 'count' || y.unit === 'count') return `Off by ${Math.round(d)}`
  const pct = (d / Math.max(Math.abs(a), Math.abs(b), 1e-9)) * 100
  return `Off by ${pct < 10 ? pct.toFixed(1) : Math.round(pct)}%`
}

export function CrossCheck({ answer: a, engine, gemma }: { answer: Answer; engine: Engine; gemma?: GemmaState }) {
  const m = side(a, 'measure', engine, gemma)
  const g = side(a, 'model', engine, gemma)
  const v = verdict(a, m, g)
  const used = a.status === 'cannot_verify' ? null : a.source
  return (
    <section className={`cx is-${v.kind}`} aria-label="Cross-check">
      <LaneCell s={m} used={used} held={a.status === 'cannot_verify'} />
      <div className="cx-verdict" role="status">
        <span className="cx-sign" aria-hidden="true">{{ agree: '=', differ: '≠', single: '·', none: '×' }[v.kind]}</span>
        <strong>{v.title}</strong>
        <span>{v.sub}</span>
      </div>
      <LaneCell s={g} used={used} held={a.status === 'cannot_verify'} />
    </section>
  )
}

function LaneCell({ s, used, held }: { s: Side; used: Source | null; held: boolean }) {
  const off = !s.got || s.got.answer == null
  return (
    <div className={`cx-lane is-${s.lane}${off ? ' is-off' : ''}${s.got && s.got.source === used ? ' is-used' : ''}`}>
      <span className="cx-who">{s.got ? NAME[s.got.source] : s.lane === 'measure' ? 'Geometry' : 'Gemma'}</span>
      <span className="cx-how">{s.got ? HOW[s.got.source] : s.lane === 'measure' ? 'Measures the drawing’s data' : 'Looks at the image'}</span>
      {s.got && s.got.answer != null ? (
        <>
          <span className={`cx-val${held ? ' is-held' : ''}`}>{formatValue(s.got.answer, s.got.unit)}</span>
          <span className="cx-conf">{held ? 'Held back · ' : ''}score {Math.round(s.got.confidence * 100)}%</span>
        </>
      ) : (
        <>
          <span className="cx-val">—</span>
          <span className="cx-conf">{s.why ?? 'No answer'}</span>
        </>
      )}
    </div>
  )
}
