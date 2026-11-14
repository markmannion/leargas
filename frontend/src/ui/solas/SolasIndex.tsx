import { useEffect, useRef, useState } from 'react'
import type { Drawing } from '../../types'
import { FORMAT_LABEL, collectionName, drawingName, useCatalogue } from '../../core/catalogue'

interface Props {
  drawings: Drawing[]
  selected: string | null
  loading: boolean
  error: string | null
  onSelect: (d: Drawing) => void
  onAdd: () => void
  onClose: () => void
}

const PAGE = 120

export function SolasIndex({ drawings, selected, loading, error, onSelect, onAdd, onClose }: Props) {
  const c = useCatalogue(drawings)
  const [limit, setLimit] = useState(PAGE)
  const [cursor, setCursor] = useState(0)
  const search = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLOListElement>(null)
  const rows = c.results.slice(0, limit)

  useEffect(() => { search.current?.focus() }, [])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  useEffect(() => {
    list.current?.querySelector('[data-cursor]')?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  const reset = () => { setLimit(PAGE); setCursor(0) }

  return (
    <div className="si" role="dialog" aria-modal="true" aria-label="Choose a drawing">
      <div className="si-top">
        <input ref={search} type="search" className="si-search" value={c.query}
          placeholder={loading ? 'Loading drawings' : `Search ${drawings.length.toLocaleString()} drawings`}
          aria-label="Search drawings by site, building, floor or file name"
          onChange={(e) => { c.setQuery(e.target.value); reset() }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((n) => Math.min(rows.length - 1, n + 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((n) => Math.max(0, n - 1)) }
            if (e.key === 'Enter' && rows[cursor]) { e.preventDefault(); onSelect(rows[cursor]) }
          }} />
        <button type="button" className="si-close" onClick={onClose}>Close</button>
      </div>
      <div className="si-filters">
        <button type="button" aria-pressed={!c.collection} onClick={() => { c.setCollection(''); reset() }}>Everything</button>
        {c.collections.map(([name, n]) => (
          <button key={name} type="button" aria-pressed={c.collection === name} onClick={() => { c.setCollection(name); reset() }}>
            {collectionName(name)} <span>{n.toLocaleString()}</span>
          </button>
        ))}
        {c.formats.length > 1 && <span className="si-sep" aria-hidden="true" />}
        {c.formats.length > 1 && c.formats.map((f) => (
          <button key={f} type="button" aria-pressed={c.format === f} onClick={() => { c.setFormat(c.format === f ? '' : f); reset() }}>
            {FORMAT_LABEL[f]}
          </button>
        ))}
        <button type="button" className="si-add" onClick={onAdd}>Add your own drawing</button>
      </div>

      {error && <p className="si-msg">The drawings could not be loaded: {error}</p>}
      {!error && !loading && !rows.length && (
        <p className="si-msg">Nothing matches.{c.filtered && <> <button type="button" onClick={() => { c.clear(); reset() }}>Show everything</button></>}</p>
      )}
      <ol className="si-list" ref={list}>
        {rows.map((d, i) => {
          const [main, sub] = drawingName(d.name)
          return (
            <li key={d.path}>
              <button type="button" onClick={() => onSelect(d)} onPointerMove={() => cursor !== i && setCursor(i)}
                aria-current={d.path === selected ? 'true' : undefined} data-cursor={i === cursor ? '' : undefined} title={d.path}>
                <span className="si-name">{main}</span>
                <span className="si-sub">{sub || collectionName(d.collection)}</span>
                <span className="si-meta">
                  {FORMAT_LABEL[d.render]}
                  {d.collection !== 'uploads' && <> · {d.questions.length} questions</>}
                </span>
              </button>
            </li>
          )
        })}
      </ol>
      {c.results.length > limit && (
        <button type="button" className="si-more" onClick={() => setLimit((n) => n + PAGE)}>
          Show more ({limit.toLocaleString()} of {c.results.length.toLocaleString()})
        </button>
      )}
    </div>
  )
}
