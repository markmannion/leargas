import type { DatasetQuestion, QuestionType, Source, Status, Unit } from './types'

export const UNIT_LABEL: Record<Unit, string> = {
  count: '',
  m: 'm',
  m2: 'm²',
  m3: 'm³',
  ft: 'ft',
  ft2: 'ft²',
  ft3: 'ft³',
}

export const SOURCE_LABEL: Record<Source, string> = {
  geometry_dxf: 'Geometry · DXF',
  geometry_ifc: 'Geometry · IFC',
  gemma_ft: 'Gemma · fine-tuned',
  gemma_base: 'Gemma · base',
  mock: 'Mock',
}

export const STATUS_LABEL: Record<Status, string> = {
  verified: 'Verified',
  partial: 'Partial',
  disagreement: 'Disagreement',
  cannot_verify: 'Cannot verify',
}

export const STATUS_NOTE: Record<Status, string> = {
  verified: 'One confident source, or two that agree.',
  partial: 'Answered, but the evidence only partly supports it.',
  disagreement: 'Geometry and the model both answered and differ.',
  cannot_verify: 'No source was confident enough to answer.',
}

export function formatValue(v: number | string | null, unit: Unit | null | undefined): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  const n = Number.isInteger(v) ? v.toString() : v.toFixed(v >= 100 ? 1 : 2)
  const u = unit ? UNIT_LABEL[unit] : ''
  return u ? `${n} ${u}` : n
}

const TO_METRIC: Partial<Record<Unit, number>> = { ft: 0.3048, ft2: 0.09290304, ft3: 0.028316846592 }

/** Same rule as backend/score.py: counts exact, measures within 2%. */
export function matchesReference(
  pred: number | string | null,
  predUnit: Unit | null,
  ref: DatasetQuestion,
): boolean | null {
  if (pred === null || ref.answer === null) return null
  if (ref.type === 'text' || typeof pred === 'string' || typeof ref.answer === 'string') {
    return String(pred).trim().toLowerCase() === String(ref.answer).trim().toLowerCase()
  }
  if (ref.type === 'count') return Number(pred) === Number(ref.answer)
  const a = pred * (predUnit ? TO_METRIC[predUnit] ?? 1 : 1)
  const b = ref.answer * (ref.unit ? TO_METRIC[ref.unit] ?? 1 : 1)
  if (b === 0) return a === 0
  return Math.abs(a - b) / Math.abs(b) <= 0.02
}

export const TYPE_LABEL: Record<QuestionType, string> = {
  count: 'Count',
  area: 'Area',
  length: 'Length',
  volume: 'Volume',
  text: 'Text',
  other: 'Other',
}

/** Rough language tag for a dataset question, so the list can show it. */
export function guessLang(q: string): string {
  // English questions quote German room names ('Küche'), so check English first.
  if (/^(how|what|which|is|are|does|do|in|on)\b/i.test(q.trim())) return 'EN'
  if (/[äöüß«»]|\b(wie|viele|der|die|das|auf|diesem)\b/i.test(q)) return 'DE'
  if (/\b(kuinka|monta|pohjapiirustuksessa|huonetta)\b/i.test(q)) return 'FI'
  if (/\b(combien|pièces|sur ce plan|surface)\b/i.test(q)) return 'FR'
  if (/\b(quanti|quante|questa|pianta)\b/i.test(q)) return 'IT'
  if (/\b(hvor|mange|på denne)\b/i.test(q)) return 'DA'
  if (/\b(hur|många|denna)\b/i.test(q)) return 'SV'
  return 'EN'
}
