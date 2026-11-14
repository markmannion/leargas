import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Evidence, Source } from '../types'

// The sheet is laid out at a fixed base width; evidence (normalized 0–1) is drawn in the same
// pixel space, so markers keep their size and the overlay lines up at every zoom level.
const BASE_W = 1000
const MIN_ZOOM = 0.1
const MAX_ZOOM = 12

interface Props {
  src: string | null
  evidence: Evidence[]
  page: number
  hovered: number | null
  onHover: (i: number | null) => void
  renderNote?: string | null
}

interface View {
  x: number
  y: number
  k: number
}

export function sourceClass(s?: Source | null): string {
  if (s === 'geometry_dxf' || s === 'geometry_ifc') return 'src-geometry'
  if (s === 'gemma_ft' || s === 'gemma_base') return 'src-model'
  return 'src-mock'
}

export function SheetViewer({ src, evidence, page, hovered, onHover, renderNote }: Props) {
  const frame = useRef<HTMLDivElement>(null)
  const [aspect, setAspect] = useState<number | null>(null) // height / width
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 })
  const [cursor, setCursor] = useState<[number, number] | null>(null)
  const [showEvidence, setShowEvidence] = useState(true)
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  const [dragging, setDragging] = useState(false)

  const H = aspect ? BASE_W * aspect : 0

  const fit = useCallback(() => {
    const el = frame.current
    if (!el || !aspect) return
    const pad = 32
    const w = el.clientWidth - pad * 2
    const h = el.clientHeight - pad * 2
    const k = Math.min(w / BASE_W, h / (BASE_W * aspect))
    setView({ k, x: (el.clientWidth - BASE_W * k) / 2, y: (el.clientHeight - BASE_W * aspect * k) / 2 })
  }, [aspect])

  useEffect(() => {
    setAspect(null)
    setState(src ? 'loading' : 'idle')
  }, [src])

  useLayoutEffect(() => {
    fit()
  }, [fit])

  useEffect(() => {
    const el = frame.current
    if (!el) return
    const ro = new ResizeObserver(() => fit())
    ro.observe(el)
    return () => ro.disconnect()
  }, [fit])

  // Wheel zoom around the cursor. Registered natively so preventDefault works (non-passive).
  useEffect(() => {
    const el = frame.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const mx = e.clientX - r.left
      const my = e.clientY - r.top
      setView((v) => {
        const k = clamp(v.k * Math.exp(-e.deltaY * 0.0015), MIN_ZOOM, MAX_ZOOM)
        return { k, x: mx - ((mx - v.x) * k) / v.k, y: my - ((my - v.y) * k) / v.k }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const zoomBy = (f: number) => {
    const el = frame.current
    if (!el) return
    const mx = el.clientWidth / 2
    const my = el.clientHeight / 2
    setView((v) => {
      const k = clamp(v.k * f, MIN_ZOOM, MAX_ZOOM)
      return { k, x: mx - ((mx - v.x) * k) / v.k, y: my - ((my - v.y) * k) / v.k }
    })
  }

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
    setDragging(true)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const el = frame.current
    if (!el) return
    if (drag.current) {
      const d = drag.current
      setView((v) => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y }))
    }
    if (aspect) {
      const r = el.getBoundingClientRect()
      const nx = (e.clientX - r.left - view.x) / view.k / BASE_W
      const ny = (e.clientY - r.top - view.y) / view.k / H
      setCursor(nx >= 0 && nx <= 1 && ny >= 0 && ny <= 1 ? [nx, ny] : null)
    }
  }
  const onPointerUp = () => {
    drag.current = null
    setDragging(false)
  }

  const visible = evidence.map((e, i) => ({ e, i })).filter(({ e }) => (e.page ?? 0) === page)

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        <div className="tool-group">
          <button className="tool" onClick={() => zoomBy(1 / 1.25)} title="Zoom out" aria-label="Zoom out">
            −
          </button>
          <span className="zoom-readout mono">{Math.round(view.k * 100)}%</span>
          <button className="tool" onClick={() => zoomBy(1.25)} title="Zoom in" aria-label="Zoom in">
            +
          </button>
          <button className="tool text" onClick={fit} title="Fit sheet to view">
            Fit
          </button>
        </div>
        <label className="toggle">
          <input type="checkbox" checked={showEvidence} onChange={(e) => setShowEvidence(e.target.checked)} />
          <span>Evidence layer</span>
          <span className="count mono">{visible.length}</span>
        </label>
      </div>

      <div
        ref={frame}
        className={`viewer-frame${dragging ? ' dragging' : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => {
          onPointerUp()
          setCursor(null)
        }}
        onDoubleClick={fit}
      >
        {!src && <div className="viewer-empty">Select a drawing from the register.</div>}
        {src && state === 'error' && (
          <div className="viewer-empty">
            The sheet could not be loaded.
            <br />
            <span className="muted">Is the backend running, and is the drawing available locally?</span>
          </div>
        )}
        {src && state === 'loading' && <div className="viewer-empty muted">Loading sheet…</div>}

        {src && (
          <div
            className="sheet"
            style={{
              width: BASE_W,
              height: H || undefined,
              transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`,
              visibility: state === 'ready' ? 'visible' : 'hidden',
            }}
          >
            <img
              key={src}
              src={src}
              alt="Drawing sheet"
              draggable={false}
              onLoad={(e) => {
                const img = e.currentTarget
                setAspect(img.naturalWidth ? img.naturalHeight / img.naturalWidth : 1)
                setState('ready')
              }}
              onError={() => setState('error')}
            />
            {aspect && showEvidence && (
              <svg className="overlay" viewBox={`0 0 ${BASE_W} ${H}`} width={BASE_W} height={H}>
                {visible.map(({ e, i }) => (
                  <EvidenceMark
                    key={i}
                    ev={e}
                    index={i}
                    w={BASE_W}
                    h={H}
                    k={view.k}
                    active={hovered === i}
                    dimmed={hovered !== null && hovered !== i}
                    onHover={onHover}
                  />
                ))}
              </svg>
            )}
          </div>
        )}
      </div>

      <div className="viewer-status mono">
        <span>{cursor ? `x ${cursor[0].toFixed(3)}  y ${cursor[1].toFixed(3)}` : 'x —  y —'}</span>
        {renderNote && <span className="render-note">{renderNote}</span>}
        <span className="hint">Drag to pan · scroll to zoom · double-click to fit</span>
      </div>
    </div>
  )
}

function EvidenceMark({
  ev,
  index,
  w,
  h,
  k,
  active,
  dimmed,
  onHover,
}: {
  ev: Evidence
  index: number
  w: number
  h: number
  k: number
  active: boolean
  dimmed: boolean
  onHover: (i: number | null) => void
}) {
  // Markers are sized in screen pixels: divide by zoom so they don't balloon when zoomed in.
  const s = 1 / k
  const cls = `mark ${sourceClass(ev.source)}${active ? ' active' : ''}${dimmed ? ' dimmed' : ''}`
  const handlers = {
    onPointerEnter: () => onHover(index),
    onPointerLeave: () => onHover(null),
  }
  const shape = ev.shape
  let anchor: [number, number]
  let body: React.ReactNode

  if (shape.kind === 'point') {
    const [x, y] = [shape.point[0] * w, shape.point[1] * h]
    anchor = [x, y]
    body = (
      <>
        <circle cx={x} cy={y} r={9 * s} className="mark-halo" />
        <circle cx={x} cy={y} r={4 * s} className="mark-dot" />
      </>
    )
  } else if (shape.kind === 'bbox') {
    const [x0, y0, x1, y1] = shape.bbox
    anchor = [x0 * w, y0 * h]
    body = (
      <rect
        x={x0 * w}
        y={y0 * h}
        width={(x1 - x0) * w}
        height={(y1 - y0) * h}
        className="mark-area"
        strokeWidth={1.5 * s}
      />
    )
  } else {
    const pts = shape.points.map(([x, y]) => `${x * w},${y * h}`).join(' ')
    anchor = [shape.points[0][0] * w, shape.points[0][1] * h]
    body = <polygon points={pts} className="mark-area" strokeWidth={1.5 * s} />
  }

  const tag = String(index + 1)
  const tw = (tag.length * 7 + 8) * s
  return (
    <g className={cls} {...handlers}>
      {body}
      <g transform={`translate(${anchor[0] + 6 * s}, ${anchor[1] - 18 * s})`}>
        <rect width={tw} height={14 * s} className="mark-tag" />
        <text x={tw / 2} y={10.5 * s} fontSize={10 * s} className="mark-tag-text">
          {tag}
        </text>
      </g>
    </g>
  )
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v))
}
