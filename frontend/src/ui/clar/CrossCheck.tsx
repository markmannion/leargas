import type { ReactNode } from 'react'
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

export function CrossCheck({ answer: a, engine, gemma, children }: {
  answer: Answer
  engine: Engine
  gemma?: GemmaState
  children: ReactNode // the result, which the two lanes flow into
}) {
  const m = side(a, 'measure', engine, gemma)
  const g = side(a, 'model', engine, gemma)
  const v = verdict(a, m, g)
  const used = a.status === 'cannot_verify' ? null : a.source
  return (
    <section className={`cxw is-${v.kind}`} aria-label="Cross-check">
      <div className="cx">
        <LaneCell s={m} used={used} held={a.status === 'cannot_verify'} />
        <div className="cx-verdict" role="status">
          <span className="cx-sign" aria-hidden="true">{{ agree: '=', differ: '≠', single: '·', none: '×' }[v.kind]}</span>
          <strong>{v.title}</strong>
          <span>{v.sub}</span>
        </div>
        <LaneCell s={g} used={used} held={a.status === 'cannot_verify'} />
      </div>
      <Flow m={flowOf(m, used, v.kind)} g={flowOf(g, used, v.kind)} agree={v.kind === 'agree'} />
      <div className="cx-result">{children}</div>
    </section>
  )
}

// How a lane reaches the result: 'in' feeds it, 'out' answered but was overruled or held back,
// 'none' had nothing to give.
type FlowState = 'in' | 'out' | 'none'

function flowOf(s: Side, used: Source | null, kind: Verdict['kind']): FlowState {
  if (!s.got || s.got.answer == null) return 'none'
  if (kind === 'agree') return 'in'
  return used !== null && s.got.source === used ? 'in' : 'out'
}

// Lane centres in a 0-100 wide box (the strip is a fixed width: lanes 1fr, verdict 84px).
const X = { measure: 19.4, model: 80.6 }

function Flow({ m, g, agree }: { m: FlowState; g: FlowState; agree: boolean }) {
  const line = (lane: 'measure' | 'model', st: FlowState) => {
    const x = X[lane]
    if (st === 'in') return <path key={lane} className={`cx-f is-${lane}`} d={`M${x} 0 V4 C${x} 22, 50 10, 50 30`} />
    if (st === 'out') {
      return (
        <g key={lane} className={`cx-f is-${lane} is-out`}>
          <path d={`M${x} 0 V11`} />
          <path className="cx-x" d={`M${x - 1.1} 12 L${x + 1.1} 17 M${x + 1.1} 12 L${x - 1.1} 17`} />
        </g>
      )
    }
    return <path key={lane} className={`cx-f is-${lane} is-none`} d={`M${x} 0 V7`} />
  }
  const fed = m === 'in' || g === 'in'
  return (
    <div className={`cx-flow${fed ? '' : ' is-dry'}`} aria-hidden="true">
      <svg viewBox="0 0 100 30" preserveAspectRatio="none">
        {line('measure', m)}
        {line('model', g)}
        {agree && <path className="cx-f is-ink" d="M50 0 V30" />}
      </svg>
      <span className="cx-arrow" />
    </div>
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
