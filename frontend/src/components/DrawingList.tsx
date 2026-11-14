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
    <aside className="register" aria-label="Drawing library">
      <div className="register-head">
        <h2 className="panel-title">
          Drawings <span className="muted">{total.toLocaleString()}</span>
        </h2>
        <input
          type="search"
          className="search"
          placeholder="Find a drawing…"
          aria-label="Search drawings"
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
            <div className="group-label">{collection.replace(/_/g, ' ')}</div>
            <ul>
              {items.map((d) => (
                <li key={d.path}>
                  <button
                    className={`sheet-row${selected === d.path ? ' on' : ''}`}
                    aria-current={selected === d.path ? true : undefined}
                    onClick={() => onSelect(d)}
                    title={d.path}
                  >
                    <svg className="sheet-icon" width="18" height="22" viewBox="0 0 18 22" fill="none" stroke="currentColor" aria-hidden="true"><path d="M3 1h8l4 4v16H3zM11 1v5h4M6 11h6M6 15h4" /></svg>
                    <span className="sheet-text">
                      <span className="sheet-name">{prettyName(d.name)[0]}</span>
                      <span className="sheet-sub">{prettyName(d.name)[1]}</span>
                    </span>
                    <span className="sheet-meta">
                      <span className="badge">{RENDER_LABEL[d.render]}</span>
                      <span className="qcount" title={`${d.questions.length} questions`}>
                        {d.questions.length}
                      </span>
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

// site1000_bldg2082_floor9385 → ["Site 1000", "Building 2082 · Floor 9385"]
function prettyName(name: string): [string, string] {
  const m = name.match(/^site(\d+)_bldg(\d+)_floor(\d+)$/)
  return m ? [`Site ${m[1]}`, `Building ${m[2]} · Floor ${m[3]}`] : [name, '']
}
