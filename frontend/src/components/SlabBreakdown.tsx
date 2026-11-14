import { api } from '../api'
import type { Answer } from '../types'

export function SlabBreakdown({ answer, onHover }: { answer: Answer; onHover: (index: number | null) => void }) {
  const rows = answer.slab_areas ?? []
  if (!rows.length) return null
  return (
    <div className="block slab-breakdown">
      <h3 className="block-title">Slab area by thickness and reinforcement</h3>
      <div className="slab-table-scroll">
        <table className="room-areas slab-areas">
          <thead><tr><th scope="col">Thickness</th><th scope="col">Reinforcement</th><th scope="col">Area</th></tr></thead>
          <tbody>{(answer.slab_groups ?? []).map((group, i) => (
            <tr key={i}>
              <th scope="row">{group.thickness_mm == null ? 'Unknown thickness' : `${group.thickness_mm} mm`}</th>
              <td>{group.reinforcement ?? 'Unknown specification'}
                {group.specification_status === 'unknown' && group.reinforcement && <small>Unknown specification</small>}
              </td>
              <td className="mono num" title={`${group.value} m²`}>{group.value.toFixed(2)} m²</td>
            </tr>
          ))}</tbody>
          <tfoot><tr><th scope="row" colSpan={2}>Total slab area</th>
            <td className="mono num">{typeof answer.answer === 'number' ? `${answer.answer.toFixed(2)} m²` : '—'}</td>
          </tr></tfoot>
        </table>
      </div>
      <p className="scope-help">Unknown specifications retain their measured area. Totals use unrounded areas.</p>
      <details>
        <summary>Slabs and specification sources ({rows.length})</summary>
        <ul className="slab-records">{rows.map((row) => (
          <li key={row.id}>
            <button type="button" disabled={!row.evidence_indices.length}
              title={row.evidence_indices.length ? 'Highlight this slab zone on the plan' : 'Measured area is available; no aligned sheet outline is available.'}
              onPointerEnter={() => onHover(row.evidence_indices[0] ?? null)} onPointerLeave={() => onHover(null)}
              onFocus={() => onHover(row.evidence_indices[0] ?? null)} onBlur={() => onHover(null)}
              onClick={() => onHover(row.evidence_indices[0] ?? null)}>
              {row.mark ?? 'Unmarked slab zone'} · {row.value.toFixed(2)} m²
            </button>
            <p>{row.slab_type ?? 'Unknown type'}{row.level ? ` · ${row.level}` : ''} · {row.thickness_mm == null ? 'Unknown thickness' : `${row.thickness_mm} mm`}
              {' · '}{row.reinforcement ?? 'Unknown specification'} · {row.method === 'quantity' ? 'Model quantity' : 'CAD geometry'}</p>
            {row.warnings.map((warning, i) => <p className="scope-help" key={i}>{warning}</p>)}
            <ul>{row.references.map((ref, i) => (
              <li key={i}>{/\.(pdf|dxf|png|jpe?g)$/i.test(ref.path)
                ? <a href={api.drawingUrl(ref.path, ref.page)} target="_blank" rel="noreferrer">{ref.path.split('/').pop()} · p{ref.page + 1}</a>
                : <span>{ref.path.split('/').pop()}</span>}
                <span className="scope-help"> — {ref.label}</span>
              </li>
            ))}</ul>
          </li>
        ))}</ul>
      </details>
    </div>
  )
}
