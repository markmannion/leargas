// Plain sentences that say how an answer was reached, built only from fields in the Answer.
import type { Answer, DatasetQuestion, Source } from '../types'
import { formatValue, matchesReference } from '../format'

export const SOURCE_SHORT: Record<Source, string> = {
  geometry_dxf: 'DXF geometry',
  geometry_ifc: 'IFC model',
  gemma_ft: 'Fine-tuned Gemma',
  gemma_base: 'Base Gemma',
  sheet_reader: 'Sheet reader',
  mock: 'Mock',
}

const FROM: Record<Source, string> = {
  geometry_dxf: 'the CAD geometry in this drawing’s DXF file',
  geometry_ifc: 'the IFC building model',
  gemma_ft: 'the image, by the fine-tuned Gemma model',
  gemma_base: 'the image, by the base Gemma model',
  sheet_reader: 'the printed text and linework on the sheet',
  mock: 'the dataset answer (the API is in mock mode)',
}

export const isModel = (s: Source) => s === 'gemma_ft' || s === 'gemma_base'

export function value(a: Answer) {
  if (a.answer === null) return '—'
  const areaLike = typeof a.answer === 'number' && ((a.room_areas?.length ?? 0) > 0 || (a.slab_areas?.length ?? 0) > 0 || a.area_mode === 'intersection')
  return areaLike ? `${(a.answer as number).toFixed(2)} m²` : formatValue(a.answer, a.unit)
}

/** The value split into number and unit, for setting them at different sizes. */
export function valueParts(a: Answer): [string, string] {
  const v = value(a)
  const m = v.match(/^(-?[\d.,]+)\s*(.*)$/)
  return m ? [m[1], m[2]] : [v, '']
}

export function rejectedGuess(a: Answer) {
  return a.status === 'cannot_verify' ? a.sources.find((s) => s.answer !== null) ?? null : null
}

export function explain(a: Answer, ref: DatasetQuestion | null): string[] {
  const out: string[] = []
  const others = a.sources.filter((s) => s.source !== a.source && s.answer !== null)
  const pct = (c: number) => `${Math.round(c * 100)}%`

  if (a.status === 'cannot_verify') {
    const g = rejectedGuess(a)
    out.push(g
      ? `No answer. ${SOURCE_SHORT[g.source]} guessed ${formatValue(g.answer, g.unit)}, but its score (${pct(g.confidence)}) is below the level where its answers are reliable.`
      : 'No answer. No engine could read this from the drawing.')
  } else if (a.status === 'disagreement') {
    out.push(`The engines disagree: ${a.sources.map((s) => `${SOURCE_SHORT[s.source]} says ${formatValue(s.answer, s.unit)}`).join(', ')}.`)
    out.push(`This answer is the one from ${SOURCE_SHORT[a.source]}.`)
  } else {
    out.push(`${a.status === 'partial' ? 'Probably right. Read' : 'Read'} from ${FROM[a.source]}.`)
    if (a.status === 'partial') out.push('The evidence only partly supports it, so check the marks on the sheet.')
    const agree = others.filter((s) => formatValue(s.answer, s.unit) === formatValue(a.answer, a.unit))
    if (agree.length) out.push(`${agree.map((s) => SOURCE_SHORT[s.source]).join(' and ')} gave the same answer.`)
  }

  if (a.status !== 'cannot_verify' && isModel(a.source)) {
    out.push(`Model score ${pct(a.confidence)}. This comes from the model’s own output; it is not a probability that the answer is right.`)
  }

  const n = a.evidence.length
  if (n && a.status !== 'cannot_verify') {
    if (a.type === 'count' && typeof a.answer === 'number' && a.answer === n) out.push(`Each of the ${n} is marked on the sheet.`)
    else out.push(`${n} ${n === 1 ? 'mark' : 'marks'} on the sheet show where this comes from.`)
  } else if (!n && a.status !== 'cannot_verify') {
    out.push('There is nothing to mark on the sheet for this answer.')
  }

  if (ref && ref.answer !== null) {
    const m = matchesReference(a.answer, a.unit, ref)
    out.push(m === null
      ? `The dataset answer is ${formatValue(ref.answer, ref.unit)}.`
      : `The dataset answer is ${formatValue(ref.answer, ref.unit)}, which ${m ? 'matches' : 'does not match'}.`)
  }
  return out
}

/** True when a breakdown table already lists every evidence mark, so a plain evidence list would repeat it. */
export function itemised(a: Answer) {
  return (a.room_areas?.length ?? 0) > 0 || (a.openings?.length ?? 0) > 0 || (a.slab_areas?.length ?? 0) > 0
}
