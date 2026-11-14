// Semantic tables behind an answer: room areas, slab areas by type, the door/window takeoff and the
// per-engine answers. Each UI styles them through its own root class; markup stays plain.
import { api } from '../api'
import type { Answer, OpeningItem } from '../types'
import { formatValue } from '../format'
import { SOURCE_SHORT } from './explain'

interface Linked {
  answer: Answer
  hovered: number | null
  onHover: (i: number | null) => void
  onPick?: (i: number) => void
}

const m2 = (v: number) => `${v.toFixed(2)} m²`

function rowProps(index: number | null | undefined, { hovered, onHover, onPick }: Omit<Linked, 'answer'>) {
  const i = index ?? null
  return {
    className: i !== null && i === hovered ? 'is-on' : undefined,
    onPointerEnter: () => onHover(i),
    onPointerLeave: () => onHover(null),
    onClick: i !== null && onPick ? () => onPick(i) : undefined,
    'data-linked': i !== null ? '' : undefined,
  }
}

export function RoomTable(p: Linked) {
  const rooms = p.answer.room_areas ?? []
  if (!rooms.length) return null
  return (
    <table className="bd bd-rooms">
      <caption>{p.answer.area_mode === 'intersection' ? 'Floor area inside the region' : 'Floor area by room'}</caption>
      <thead><tr><th scope="col">Room</th><th scope="col">Basis</th><th scope="col" className="n">m²</th></tr></thead>
      <tbody>
        {rooms.map((r) => (
          <tr key={r.id} {...rowProps(r.evidence_indices[0], p)}>
            <th scope="row">
              {r.room_id && <span className="bd-id">{r.room_id}</span>} {r.label}
              {(r.level || !r.complete) && <small>{[r.level, !r.complete && 'part inside region'].filter(Boolean).join(' · ')}</small>}
            </th>
            <td>{r.method === 'printed' ? 'Printed' : r.method === 'quantity' ? 'Model qty' : 'Geometry'}</td>
            <td className="n">{r.value.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot><tr><th scope="row" colSpan={2}>Total, before rounding rooms</th>
        <td className="n">{typeof p.answer.answer === 'number' ? p.answer.answer.toFixed(2) : '—'}</td></tr></tfoot>
    </table>
  )
}

export function SlabTable(p: Linked) {
  const rows = p.answer.slab_areas ?? []
  if (!rows.length) return null
  return (
    <>
      <table className="bd bd-slabs">
        <caption>Slab area by type</caption>
        <thead><tr><th scope="col">Thickness</th><th scope="col">Bars</th><th scope="col">Types</th><th scope="col" className="n">m²</th></tr></thead>
        <tbody>
          {(p.answer.slab_groups ?? []).map((g, i) => (
            <tr key={i}>
              <th scope="row">{g.thickness_mm == null ? 'Unknown' : `${g.thickness_mm} mm`}</th>
              <td>{g.reinforcement ?? <span className="bd-none">not in source</span>}</td>
              <td>{g.slab_types?.length ? g.slab_types.join(', ') : <span className="bd-none">untyped</span>}</td>
              <td className="n">{g.value.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot><tr><th scope="row" colSpan={3}>Total slab area</th>
          <td className="n">{typeof p.answer.answer === 'number' ? p.answer.answer.toFixed(2) : '—'}</td></tr></tfoot>
      </table>
      <p className="bd-note">Bars come only from reinforcement in the model or a linked schedule. They are never guessed from type names.</p>
      <details className="bd-more">
        <summary>{rows.length} slab {rows.length === 1 ? 'zone' : 'zones'} and their sources</summary>
        <ul>
          {rows.map((r) => (
            <li key={r.id} {...rowProps(r.evidence_indices[0], p)}>
              <strong>{r.mark ?? 'Unmarked zone'}</strong> {m2(r.value)}
              <span>{[r.slab_type ?? 'unknown type', r.level, r.thickness_mm == null ? 'thickness unknown' : `${r.thickness_mm} mm`,
                r.reinforcement ?? 'bars not in source', r.method === 'quantity' ? 'model quantity' : 'geometry'].filter(Boolean).join(' · ')}</span>
              {r.warnings.map((w, i) => <em key={i}>{w}</em>)}
              {r.references.map((ref, i) => (
                <span key={i} className="bd-ref">
                  {/\.(pdf|dxf|png|jpe?g)$/i.test(ref.path)
                    ? <a href={api.drawingUrl(ref.path, ref.page)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{ref.path.split('/').pop()} p{ref.page + 1}</a>
                    : ref.path.split('/').pop()} — {ref.label}
                </span>
              ))}
            </li>
          ))}
        </ul>
      </details>
    </>
  )
}

export function OpeningTable(p: Linked) {
  const rows = p.answer.openings ?? []
  if (!rows.length) return null
  const kind = rows[0].kind
  const showType = rows.some((r) => r.type_mark || r.type_name)
  const showLevel = rows.some((r) => r.level)
  const showLeaves = kind === 'door' && rows.some((r) => r.leaves != null)
  const leaves = rows.reduce((n, r) => n + (r.leaves ?? 0), 0)
  const doubles = rows.filter((r) => (r.leaves ?? 0) > 1).length
  const dupes = rows.reduce((n, r) => n + r.duplicates.length, 0)
  const cell = (r: OpeningItem) => r.type_mark ?? r.type_name ?? '—'
  return (
    <>
      <table className="bd bd-openings">
        <caption>{kind === 'door' ? 'Doors' : 'Windows'}, one row each</caption>
        <thead><tr>
          <th scope="col" className="n">No.</th>
          {showType && <th scope="col">Type</th>}
          <th scope="col">Location</th>
          {showLevel && <th scope="col">Level</th>}
          {showLeaves && <th scope="col" className="n">Leaves</th>}
          <th scope="col" className="n">Width</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} {...rowProps(r.evidence_index, p)}>
              <th scope="row" className="n">{r.number}{r.mark && <small>{r.mark}</small>}</th>
              {showType && <td title={r.type_name ?? undefined}>{cell(r)}</td>}
              <td>{r.location.length ? r.location.join(' / ') : '—'}</td>
              {showLevel && <td>{r.level ?? '—'}</td>}
              {showLeaves && <td className="n">{r.leaves ?? '—'}</td>}
              <td className="n">{r.width_m != null ? `${r.width_m.toFixed(2)} m` : '—'}</td>
            </tr>
          ))}
        </tbody>
        <tfoot><tr><th scope="row" colSpan={6}>
          {rows.length} {kind}{rows.length === 1 ? '' : 's'}{showLeaves ? `, ${leaves} leaves` : ''}
        </th></tr></tfoot>
      </table>
      {(doubles > 0 || dupes > 0 || rows.every((r) => r.evidence_index == null)) && (
        <p className="bd-note">
          {doubles > 0 && `${doubles} double door${doubles > 1 ? 's' : ''} counted once. `}
          {dupes > 0 && `${dupes} symbol${dupes > 1 ? 's' : ''} drawn on top of another not counted again. `}
          {rows.every((r) => r.evidence_index == null) && 'This model is not aligned to a sheet, so nothing is marked.'}
        </p>
      )}
    </>
  )
}

export function SourceTable({ answer }: { answer: Answer }) {
  if (answer.sources.length < 2 && !(answer.status === 'cannot_verify' && answer.sources.length)) return null
  return (
    <table className="bd bd-sources">
      <caption>{answer.status === 'cannot_verify' ? 'Answers held back' : 'Each engine’s answer'}</caption>
      <tbody>
        {answer.sources.map((s, i) => (
          <tr key={i} className={s.source === answer.source && answer.status !== 'cannot_verify' ? 'is-chosen' : undefined}>
            <th scope="row">{SOURCE_SHORT[s.source]}</th>
            <td className="n">{formatValue(s.answer, s.unit)}</td>
            <td className="n bd-dim">{Math.round(s.confidence * 100)}%</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
