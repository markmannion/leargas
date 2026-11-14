import type { Answer, OpeningItem } from '../types'

interface Props {
  answer: Answer
  hovered: number | null
  onHover: (index: number | null) => void
}

/** Numbered door/window takeoff behind a count: row n matches marker n on the sheet. */
export function OpeningInventory({ answer, hovered, onHover }: Props) {
  const rows = answer.openings ?? []
  if (!rows.length) return null
  const kind = rows[0].kind
  const showType = rows.some((r) => r.type_mark || r.type_name)
  const showLevel = rows.some((r) => r.level)
  const showLeaves = kind === 'door' && rows.some((r) => r.leaves != null)
  const leaves = rows.reduce((n, r) => n + (r.leaves ?? 0), 0)
  const doubles = rows.filter((r) => (r.leaves ?? 0) > 1).length
  const dupes = rows.reduce((n, r) => n + r.duplicates.length, 0)

  return (
    <div className="block opening-inventory">
      <h3 className="block-title">
        {kind === 'door' ? 'Door' : 'Window'} inventory <span className="mono muted">{rows.length}</span>
      </h3>
      <p className="scope-help">
        One row per physical {kind}{kind === 'door' ? '; a double door is one row with two leaves' : ''}.
        {rows.some((r) => r.evidence_index != null) ? ' Hover a row to find its marker.' : ' This model is not aligned to a sheet, so there are no markers.'}
      </p>
      <div className="slab-table-scroll">
        <table className="room-areas opening-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              {showType && <th scope="col">Type</th>}
              <th scope="col">Location</th>
              {showLevel && <th scope="col">Level</th>}
              {showLeaves && <th scope="col">Leaves</th>}
              <th scope="col">Width</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Row key={row.id} row={row} hovered={hovered} onHover={onHover}
                showType={showType} showLevel={showLevel} showLeaves={showLeaves} />
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={3 + (showType ? 1 : 0) + (showLevel ? 1 : 0) + (showLeaves ? 1 : 0)}>
                Total: <span className="mono">{rows.length}</span> {kind}{rows.length === 1 ? '' : 's'}
                {showLeaves && <>, <span className="mono">{leaves}</span> leaves</>}
              </th>
            </tr>
          </tfoot>
        </table>
      </div>
      {(doubles > 0 || dupes > 0) && (
        <p className="scope-help">
          {doubles > 0 && `${doubles} double door${doubles > 1 ? 's' : ''} counted once. `}
          {dupes > 0 && `${dupes} duplicate symbol${dupes > 1 ? 's' : ''} drawn on top of another not counted again.`}
        </p>
      )}
    </div>
  )
}

function Row({ row, hovered, onHover, showType, showLevel, showLeaves }: {
  row: OpeningItem
  hovered: number | null
  onHover: (index: number | null) => void
  showType: boolean
  showLevel: boolean
  showLeaves: boolean
}) {
  const index = row.evidence_index ?? null
  const active = index !== null && index === hovered
  const type = row.type_mark ?? row.type_name
  return (
    <tr className={active ? 'active' : undefined}
      onPointerEnter={() => onHover(index)} onPointerLeave={() => onHover(null)}>
      <th scope="row" className="mono">
        {row.number}
        {row.mark && <small>{row.mark}</small>}
      </th>
      {showType && (
        <td title={row.type_name ?? undefined}>
          {type ?? '—'}
          {row.type_mark && row.type_name && row.type_name !== row.type_mark && <small>{row.type_name}</small>}
        </td>
      )}
      <td>{row.location.length ? row.location.join(' / ') : '—'}</td>
      {showLevel && <td>{row.level ?? '—'}</td>}
      {showLeaves && <td className="mono num">{row.leaves ?? '—'}</td>}
      <td className="mono num">{row.width_m != null ? `${row.width_m.toFixed(2)} m` : '—'}</td>
    </tr>
  )
}
