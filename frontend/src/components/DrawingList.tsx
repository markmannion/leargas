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

export function DrawingList({ drawings, total, selected, error, onSelect }: Props) {
  const [q, setQ] = useState('')
  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase()
    return t ? drawings.filter((d) => d.path.toLowerCase().includes(t)) : drawings
  }, [drawings, q])

  // Group by collection, keep order.
  const groups = useMemo(() => {
    const m = new Map<string, Drawing[]>()
    for (const d of filtered.slice(0, 400)) {
      const g = m.get(d.collection) ?? []
      g.push(d)
      m.set(d.collection, g)
    }
    return [...m.entries()]
  }, [filtered])

  return (
    <aside className="register">
      <div className="register-head">
        <h2 className="panel-title">
          Drawing register <span className="mono muted">{total}</span>
        </h2>
        <input
          type="search"
          className="search"
          placeholder="Filter by site, building, floor…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="register-body">
        {error && <p className="register-msg error">Could not load drawings: {error}</p>}
        {!error && drawings.length === 0 && <p className="register-msg muted">Loading…</p>}
        {!error && drawings.length > 0 && filtered.length === 0 && (
          <p className="register-msg muted">No drawings match “{q}”.</p>
        )}
        {groups.map(([collection, items]) => (
          <div key={collection} className="register-group">
            <div className="group-label mono">{collection}</div>
            <ul>
              {items.map((d) => (
                <li key={d.path}>
                  <button
                    className={`sheet-row${selected === d.path ? ' on' : ''}`}
                    onClick={() => onSelect(d)}
                    title={d.path}
                  >
                    <span className="sheet-name mono">{prettyName(d.name)}</span>
                    <span className="sheet-meta mono">
                      {RENDER_LABEL[d.render]} · {d.questions.length}q
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
        {filtered.length > 400 && (
          <p className="register-msg muted small">Showing 400 of {filtered.length}. Narrow the filter.</p>
        )}
      </div>
    </aside>
  )
}

// site1000_bldg2082_floor9385 → S1000 · B2082 · F9385
function prettyName(name: string) {
  const m = name.match(/^site(\d+)_bldg(\d+)_floor(\d+)$/)
  return m ? `S${m[1]} · B${m[2]} · F${m[3]}` : name
}
