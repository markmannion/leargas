import { useMemo, useState } from 'react'
import type { Drawing } from '../types'

interface Props {
  drawings: Drawing[]
  total: number
  selected: string | null
  error: string | null
  onSelect: (d: Drawing) => void
}

const RENDER_LABEL: Record<Drawing['render'], string> = { image: 'IMG', pdf: 'PDF', dxf: 'DXF' }
const PAGE_SIZE = 80
const naturalOrder = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

function collectionName(collection: string) {
  return collection.replace(/[_-]/g, ' ') || 'Other plans'
}

function searchText(text: string) {
  return text.toLowerCase().replace(/([a-z])(\d)/g, '$1 $2').replace(/[^\p{L}\p{N}]+/gu, ' ')
}

export function DrawingList({ drawings, total, selected, error, onSelect }: Props) {
  const [q, setQ] = useState('')
  const [collection, setCollection] = useState('')
  const [format, setFormat] = useState<Drawing['render'] | ''>('')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const collections = useMemo(() => {
    const counts = new Map<string, number>()
    for (const drawing of drawings) counts.set(drawing.collection, (counts.get(drawing.collection) ?? 0) + 1)
    return [...counts].sort(([a], [b]) => naturalOrder.compare(a, b))
  }, [drawings])
  const formats = useMemo(() => [...new Set(drawings.map((drawing) => drawing.render))], [drawings])
  const filtered = useMemo(() => {
    const terms = searchText(q).split(' ').filter(Boolean)
    return drawings.filter((drawing) => {
      if (collection && drawing.collection !== collection) return false
      if (format && drawing.render !== format) return false
      const searchable = searchText(`${drawing.path} ${prettyName(drawing.name).join(' ')} ${drawing.render}`)
      return terms.every((term) => searchable.includes(term))
    }).sort((a, b) => naturalOrder.compare(a.collection, b.collection) || naturalOrder.compare(a.name, b.name))
  }, [drawings, q, collection, format])
  const current = drawings.find((drawing) => drawing.path === selected)
  const hasFilters = Boolean(q || collection || format)

  function clearFilters() {
    setQ('')
    setCollection('')
    setFormat('')
    setVisibleCount(PAGE_SIZE)
  }

  const groups = useMemo(() => {
    const m = new Map<string, Drawing[]>()
    for (const d of filtered.slice(0, visibleCount)) {
      const g = m.get(d.collection) ?? []
      g.push(d)
      m.set(d.collection, g)
    }
    return [...m.entries()]
  }, [filtered, visibleCount])

  return (
    <aside className="register glass" aria-label="Plan library">
      <div className="register-head">
        <h2 className="panel-title">
          Plans <span className="muted">{total.toLocaleString()}</span>
        </h2>
        <p className="register-help">Find a plan to start exploring.</p>
        <input
          type="search"
          className="search"
          placeholder="Search site, building, floor…"
          aria-label="Search plans by name, site, building or floor"
          value={q}
          onChange={(e) => { setQ(e.target.value); setVisibleCount(PAGE_SIZE) }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && filtered[0]) { e.preventDefault(); onSelect(filtered[0]) }
            if (e.key === 'Escape') { setQ(''); setVisibleCount(PAGE_SIZE) }
          }}
        />
        <label className="plan-collection">
          <span>Collection</span>
          <select
            value={collection}
            onChange={(e) => { setCollection(e.target.value); setVisibleCount(PAGE_SIZE) }}
          >
            <option value="">All collections ({drawings.length.toLocaleString()})</option>
            {collections.filter(([name]) => name).map(([name, count]) => (
              <option key={name} value={name}>{collectionName(name)} ({count.toLocaleString()})</option>
            ))}
          </select>
        </label>
        {formats.length > 1 && (
          <div className="plan-formats" role="group" aria-label="Filter by plan format">
            {(['', ...formats] as const).map((kind) => (
              <button
                key={kind || 'all'}
                type="button"
                aria-pressed={format === kind}
                className={format === kind ? 'on' : ''}
                onClick={() => { setFormat(kind); setVisibleCount(PAGE_SIZE) }}
              >{kind ? RENDER_LABEL[kind] : 'All formats'}</button>
            ))}
          </div>
        )}
        {current && (
          <div className="plan-current" title={current.path}>
            <span className="plan-current-label">Viewing now</span>
            <span className="plan-current-name">{prettyName(current.name).filter(Boolean).join(' · ')}</span>
          </div>
        )}
        <div className="plan-results">
          <span role="status">{filtered.length.toLocaleString()} {filtered.length === 1 ? 'plan' : 'plans'}{hasFilters ? ' found' : ' available'}</span>
          {hasFilters && <button type="button" onClick={clearFilters}>Clear filters</button>}
        </div>
      </div>

      <div className="register-body">
        {error && <p className="register-msg error">Could not load drawings: {error}</p>}
        {!error && drawings.length === 0 && <p className="register-msg muted">Loading…</p>}
        {!error && drawings.length > 0 && filtered.length === 0 && (
          <div className="register-empty">
            <strong>No matching plans</strong>
            <p>Try another name or choose a different collection.</p>
            <button type="button" onClick={clearFilters}>Show all plans</button>
          </div>
        )}
        {groups.map(([collection, items]) => (
          <div key={collection} className="register-group">
            <div className="group-label">{collectionName(collection)}</div>
            <ul>
              {items.map((d) => (
                <li key={d.path}>
                  <button
                    className={`sheet-row${selected === d.path ? ' on' : ''}`}
                    type="button"
                    aria-current={selected === d.path ? 'true' : undefined}
                    onClick={() => onSelect(d)}
                    title={d.path}
                  >
                    <span className="sheet-text">
                      <span className="sheet-name">{prettyName(d.name)[0]}</span>
                      <span className="sheet-sub">{prettyName(d.name)[1] || collectionName(d.collection)}</span>
                    </span>
                    <span className="sheet-meta">
                      <span className="badge">{RENDER_LABEL[d.render]}</span>
                      <span className="qcount" title={`${d.questions.length} example questions`} aria-label={`${d.questions.length} example questions`}>
                        {d.questions.length} Q
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {filtered.length > visibleCount && (
          <button className="plan-load-more" type="button" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>
            Show {Math.min(PAGE_SIZE, filtered.length - visibleCount)} more plans
            <span>{visibleCount.toLocaleString()} of {filtered.length.toLocaleString()}</span>
          </button>
        )}
        {drawings.length < total && <p className="register-msg muted small">Searching {drawings.length.toLocaleString()} of {total.toLocaleString()} plans loaded.</p>}
      </div>
    </aside>
  )
}

// Put the floor first so similar plans are easy to distinguish while browsing.
function prettyName(name: string): [string, string] {
  const m = name.match(/^site(\d+)_bldg(\d+)_floor(\d+)$/)
  return m ? [`Floor ${m[3]}`, `Site ${m[1]} · Building ${m[2]}`] : [name.replace(/_/g, ' '), '']
}
