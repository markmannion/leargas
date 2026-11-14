import { useMemo, useState } from 'react'
import type { DatasetQuestion, Drawing } from '../types'
import { guessLang } from '../format'

const naturalOrder = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

export const FORMAT_LABEL: Record<Drawing['render'], string> = { image: 'PNG', pdf: 'PDF', dxf: 'DXF', none: 'IFC' }

const COLLECTION_NAME: Record<string, string> = {
  cubicasa5k: 'CubiCasa5k',
  swiss_dwellings: 'Swiss Dwellings',
  uploads: 'Uploaded files',
}

export function collectionName(c: string) {
  if (COLLECTION_NAME[c]) return COLLECTION_NAME[c]
  const words = c.replace(/[_-]+/g, ' ').trim().replace(/\b(ifc|dxf|pdf|png|uk|us)\b/gi, (w) => w.toUpperCase())
  return words ? words[0].toUpperCase() + words.slice(1) : 'Other'
}

/** [main, secondary]: the floor first, so similar plans are easy to tell apart. */
export function drawingName(name: string): [string, string] {
  const m = name.match(/^site(\d+)_bldg(\d+)_floor(\d+)$/)
  return m ? [`Floor ${m[3]}`, `Site ${m[1]}, building ${m[2]}`] : [name.replace(/_/g, ' '), '']
}

/**
 * Vector twins (DXF / IFC) known to the frontend. Only uploads list their files; the backend also
 * finds twins for dataset drawings, so an empty result does not mean there is none.
 */
export function vectorTwins(d: Drawing): string[] {
  if (d.render === 'dxf') return ['DXF']
  if (d.render === 'none') return ['IFC']
  return (d.files ?? []).filter((f) => f === 'dxf' || f === 'ifc').map((f) => f.toUpperCase())
}

const EXT_LABEL: Record<string, string> = { png: 'PNG', jpg: 'JPEG', jpeg: 'JPEG', svg: 'SVG', pdf: 'PDF', dxf: 'DXF', ifc: 'IFC' }
const FORMAT_ORDER = ['PNG', 'JPEG', 'SVG', 'PDF', 'DXF', 'IFC']

/** The sheet's own format first, then its DXF / IFC twins: a Swiss plan is "PDF" + "DXF". */
export function formatsOf(d: Drawing): string[] {
  const ext = d.path.split('.').pop()?.toLowerCase() ?? ''
  const main = d.render === 'image' ? EXT_LABEL[ext] ?? 'PNG' : FORMAT_LABEL[d.render]
  return [...new Set([main, ...vectorTwins(d)])]
}

function searchText(text: string) {
  return text.toLowerCase().replace(/([a-z])(\d)/g, '$1 $2').replace(/[^\p{L}\p{N}]+/gu, ' ')
}

export function useCatalogue(drawings: Drawing[]) {
  const [query, setQuery] = useState('')
  const [collection, setCollection] = useState('')
  const [format, setFormat] = useState('')

  const collections = useMemo(() => {
    const counts = new Map<string, number>()
    for (const d of drawings) counts.set(d.collection, (counts.get(d.collection) ?? 0) + 1)
    return [...counts].sort(([a], [b]) => (a === 'uploads' ? -1 : b === 'uploads' ? 1 : naturalOrder.compare(a, b)))
  }, [drawings])
  const formats = useMemo(() => {
    const seen = new Set(drawings.flatMap(formatsOf))
    return FORMAT_ORDER.filter((f) => seen.has(f))
  }, [drawings])

  const results = useMemo(() => {
    const terms = searchText(query).split(' ').filter(Boolean)
    return drawings
      .filter((d) => {
        if (collection && d.collection !== collection) return false
        if (format && !formatsOf(d).includes(format)) return false
        const hay = searchText(`${d.path} ${drawingName(d.name).join(' ')} ${formatsOf(d).join(' ')}`)
        return terms.every((t) => hay.includes(t))
      })
      .sort((a, b) => (a.collection === 'uploads' ? -1 : 0) - (b.collection === 'uploads' ? -1 : 0)
        || naturalOrder.compare(a.collection, b.collection) || naturalOrder.compare(a.name, b.name))
  }, [drawings, query, collection, format])

  const filtered = Boolean(query || collection || format)
  const clear = () => { setQuery(''); setCollection(''); setFormat('') }

  return { query, setQuery, collection, setCollection, format, setFormat, collections, formats, results, filtered, clear }
}

// Starters for an upload, which has no dataset questions. They match parser templates / English
// rules, so the geometry engines can take them when the upload has a DXF or IFC twin.
const STARTERS = [
  'How many doors are drawn on this floor plan?',
  'How many windows are drawn on this floor plan?',
  'How many rooms are there?',
  'How many bathrooms are there?',
  'What is the total floor area in m²?',
]

// Door and window counts read off the image alone: gemma-ft is 14–20% right on held-out CubiCasa,
// so the router mostly declines. The DXF/IFC engines count them fine.
const RASTER_WEAK = /\b(doors?|windows?|ovea|ovi|ikkun\w*)\b/i

function rasterOnly(d: Drawing): boolean {
  if (d.files) return !d.files.some((f) => f === 'dxf' || f === 'ifc')
  return d.collection === 'cubicasa5k'
}

export interface Suggestion extends Omit<DatasetQuestion, 'answer'> {
  answer?: DatasetQuestion['answer']
  lang: string
  weak: boolean
  fromDataset: boolean
}

/** Dataset questions for this drawing (or starters for an upload), unreliable ones last. */
export function suggestionsFor(d: Drawing | null): Suggestion[] {
  if (!d) return []
  const weak = rasterOnly(d)
  const qs: Suggestion[] = d.questions.length
    ? d.questions.map((q) => ({ ...q, lang: guessLang(q.question), weak: weak && RASTER_WEAK.test(q.question), fromDataset: true }))
    : STARTERS.map((q) => ({ question: q, unit: null, type: q.includes('area') ? 'area' : 'count', lang: 'EN', weak: weak && RASTER_WEAK.test(q), fromDataset: false }))
  return [...qs.filter((q) => !q.weak), ...qs.filter((q) => q.weak)]
}
