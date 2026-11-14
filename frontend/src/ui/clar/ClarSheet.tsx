import type { Evidence, Region } from '../../types'
import type { Viewport } from '../../core/viewport'
import { cloudPath, regionPath, rowLetter, shapeAnchor, shapePath, zoneGrid } from '../../core/shapes'

interface Props {
  vp: Viewport
  evidence: Evidence[]
  showMarks: boolean
  hovered: number | null
  highlighted?: number[]
  onHover: (i: number | null) => void
  region: Region | null
  selecting: boolean
  renderNote: string | null
}

// Line style says where a mark came from, as on a drawing: solid = measured from geometry,
// dashed = estimated by the model, dotted = read from the sheet's text and lines.
function lineClass(e: Evidence) {
  if (e.source === 'gemma_ft' || e.source === 'gemma_base') return 'm-est'
  if (e.source === 'sheet_reader') return 'm-read'
  return 'm-geo'
}

export function ClarSheet({ vp, evidence, showMarks, hovered, highlighted, onHover, region, selecting, renderNote }: Props) {
  const { W, H, view, aspect, state } = vp
  const k = view.k
  const shown = selecting && vp.draft ? vp.draft : region
  const marks = showMarks ? evidence.map((e, i) => ({ e, i })).filter(({ e }) => (e.page ?? 0) === 0) : []
  const on = (i: number) => hovered === i || Boolean(highlighted?.includes(i))
  const dim = (i: number) => hovered !== null && !on(i)

  return (
    <div ref={vp.frame} className={`cl-frame${vp.dragging ? ' is-panning' : ''}${selecting ? ' is-clouding' : ''}`} {...vp.handlers}>
      {vp.imgProps.src && (
        <div className="cl-sheet" style={vp.sheetStyle}>
          <img {...vp.imgProps} key={vp.imgProps.src} alt="Drawing sheet" />
          {aspect && (
            <>
              {/* Highlighter: multiplied over the print so linework shows through. */}
              <svg className="cl-hl" viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true">
                {marks.map(({ e, i }) => e.shape.kind === 'point'
                  ? <circle key={i} cx={e.shape.point[0] * W} cy={e.shape.point[1] * H} r={8 / k} className={dim(i) ? 'is-dim' : undefined} />
                  : <path key={i} d={shapePath(e.shape, W, H)} fillRule="evenodd" className={dim(i) ? 'is-dim' : undefined} />)}
              </svg>
              <svg className="cl-ink" viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
                <rect x={0} y={0} width={W} height={H} className="cl-trim" strokeWidth={1 / k} />
                {shown && (
                  <>
                    <path d={`M0 0H${W}V${H}H0Z ${regionPath(shown, W, H)}`} fillRule="evenodd" className="cl-outside" />
                    <path d={cloudPath(shown, W, H, k)} className={`cl-cloud${selecting ? ' is-draft' : ''}`} strokeWidth={1.6 / k} />
                  </>
                )}
                {marks.map(({ e, i }) => {
                  const [ax, ay] = shapeAnchor(e.shape)
                  const tag = String(i + 1)
                  const tw = (tag.length * 6 + 8) / k
                  const cls = `cl-mark ${lineClass(e)}${on(i) ? ' is-on' : ''}${dim(i) ? ' is-dim' : ''}`
                  return (
                    <g key={i} className={cls} onPointerEnter={() => onHover(i)} onPointerLeave={() => onHover(null)}>
                      {e.shape.kind === 'point'
                        ? <circle cx={ax * W} cy={ay * H} r={8 / k} strokeWidth={(on(i) ? 2 : 1.1) / k} />
                        : <path d={shapePath(e.shape, W, H)} fillRule="evenodd" strokeWidth={(on(i) ? 2 : 1.1) / k}
                            strokeDasharray={lineClass(e) === 'm-est' ? `${5 / k} ${3 / k}` : lineClass(e) === 'm-read' ? `${1.2 / k} ${2.4 / k}` : undefined} />}
                      <g transform={`translate(${ax * W + 5 / k} ${ay * H - 17 / k})`}>
                        <rect width={tw} height={13 / k} strokeWidth={1 / k} className="cl-tag" />
                        <text x={tw / 2} y={9.6 / k} fontSize={9.5 / k} className="cl-tag-t">{tag}</text>
                      </g>
                    </g>
                  )
                })}
              </svg>
            </>
          )}
        </div>
      )}
      <ZoneRulers vp={vp} />
      <div className="cl-corner" data-no-pan>
        <button type="button" onClick={vp.fit} title="Fit the sheet to the window (or double-click the sheet)">Fit</button>
      </div>
      <div className="cl-zoom" data-no-pan role="toolbar" aria-label="Zoom">
        <button type="button" onClick={() => vp.zoomBy(1 / 1.25)} aria-label="Zoom out">−</button>
        <button type="button" onClick={() => vp.zoomBy(1.25)} aria-label="Zoom in">+</button>
      </div>
      {(selecting || renderNote) && (
        <p className="cl-note" data-no-pan>
          {selecting ? vp.hint ?? 'Drag a box on the sheet to cloud a region. Esc cancels.' : renderNote}
        </p>
      )}
      <div className="cl-empty">
        {state === 'idle' && <p>Open the drawing register to choose a sheet.</p>}
        {state === 'loading' && <p>Loading sheet…</p>}
        {state === 'error' && <p>This sheet could not be loaded. Check that the backend is running.</p>}
      </div>
    </div>
  )
}

/** Zone references along the top and left edges. They belong to the sheet, so they pan and zoom with it. */
function ZoneRulers({ vp }: { vp: Viewport }) {
  if (!vp.aspect) return null
  const { cols, rows } = zoneGrid(vp.aspect)
  const { x, y, k } = vp.view
  const cw = (vp.W * k) / cols
  const rh = (vp.H * k) / rows
  const cc = vp.cursor ? Math.min(cols - 1, Math.floor(vp.cursor[0] * cols)) : -1
  const cr = vp.cursor ? Math.min(rows - 1, Math.floor(vp.cursor[1] * rows)) : -1
  return (
    <>
      <div className="cl-ruler cl-ruler-x" aria-hidden="true">
        {Array.from({ length: cols }, (_, i) => (
          <span key={i} className={i === cc ? 'is-on' : undefined} style={{ left: x + i * cw, width: cw }}>{i + 1}</span>
        ))}
      </div>
      <div className="cl-ruler cl-ruler-y" aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => (
          <span key={i} className={i === cr ? 'is-on' : undefined} style={{ top: y + i * rh, height: rh }}>{rowLetter(i)}</span>
        ))}
      </div>
    </>
  )
}
