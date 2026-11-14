import type { Answer, Source } from '../types'

/**
 * What an answer cost to compute, as an estimate per 1,000 answers like it.
 *  - Gemma: measured throughput on one shared A100 at $2.38/h (results/throughput.json, Sat 12:25):
 *    fine-tuned 14.3 answers/s = $0.0463 per 1,000; base 11.8/s = $0.0558 per 1,000.
 *  - Geometry (DXF, IFC) and the sheet reader run on CPU only: priced at a typical on-demand
 *    $0.05 per vCPU-hour for the time the answer took.
 * Every engine the router consulted (the cross-check) is counted once.
 */
const GPU_USD_PER_ANSWER: Partial<Record<Source, number>> = {
  gemma_ft: 0.0463 / 1000,
  gemma_base: 0.0558 / 1000,
}
const CPU_USD_PER_HOUR = 0.05
const CPU_ENGINES: Source[] = ['geometry_dxf', 'geometry_ifc', 'sheet_reader']

export interface Cost {
  per1k: number
  engines: Source[]
  note: string
}

export function answerCost(a: Answer): Cost | null {
  if (a.source === 'mock') return null
  const engines = [...new Set<Source>([a.source, ...(a.sources ?? []).map((s) => s.source)])].filter((s) => s !== 'mock')
  const seconds = (a.latency_ms ?? 0) / 1000
  let usd = 0
  for (const e of engines) usd += GPU_USD_PER_ANSWER[e] ?? 0
  if (engines.some((e) => CPU_ENGINES.includes(e))) usd += (seconds * CPU_USD_PER_HOUR) / 3600
  const gpu = engines.filter((e) => e in GPU_USD_PER_ANSWER)
  const note = [
    gpu.length ? 'Gemma: measured on one shared A100 at $2.38/h (14 answers a second).' : '',
    engines.some((e) => CPU_ENGINES.includes(e)) ? 'Geometry and the sheet reader use CPU only: $0.05 per vCPU-hour for the time taken.' : '',
  ].filter(Boolean).join(' ')
  return { per1k: usd * 1000, engines, note }
}

/** "$0.046" / "$0.0012" / "under $0.0001": two significant figures, never scientific notation. */
export function formatUsd(x: number): string {
  if (x < 0.0001) return 'under $0.0001'
  const digits = Math.max(2, 1 - Math.floor(Math.log10(x)))
  return `$${x.toFixed(Math.min(digits, 6))}`
}
