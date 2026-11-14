import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Evidence, Source, Region, Pt } from '../types'

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
  region: Region | null
  selectingRegion: boolean
  onRegionChange: (region: Region | null) => void
  onSelectionModeChange: (active: boolean) => void
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

export function SheetViewer({ src, evidence, page, hovered, onHover, renderNote, region, selectingRegion, onRegionChange, onSelectionModeChange }: Props) {
  const frame = useRef<HTMLDivElement>(null)
  // Load state is keyed by src, so a cached image that loads before effects run can't be clobbered.
  const [loaded, setLoaded] = useState<{ src: string; aspect: number } | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const aspect = loaded && loaded.src === src ? loaded.aspect : null // height / width
  const state: 'idle' | 'loading' | 'ready' | 'error' = !src
    ? 'idle'
    : aspect
      ? 'ready'
      : failed === src
        ? 'error'
        : 'loading'
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 })
  const [cursor, setCursor] = useState<[number, number] | null>(null)
  const [showEvidence, setShowEvidence] = useState(true)
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  const [dragging, setDragging] = useState(false)
  const selectionStart = useRef<Pt | null>(null)
  const [draft, setDraft] = useState<Region | null>(null)
  const [selectionHint, setSelectionHint] = useState<string | null>(null)

  useEffect(() => {
    const cancel = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && selectingRegion) {
        selectionStart.current = null
        setDraft(null)
        setSelectionHint(null)
        onSelectionModeChange(false)
      }
    }
    window.addEventListener('keydown', cancel)
    return () => window.removeEventListener('keydown', cancel)
  }, [selectingRegion, onSelectionModeChange])

  const H = aspect ? BASE_W * aspect : 0

  // Panels float over the canvas; the visible area is the frame minus whatever floating panel
  // covers each edge. Stacked (mobile) panels are not absolutely positioned and don't count.
  const insets = useCallback(() => {
    const el = frame.current
    const ins = { t: 0, r: 0, b: 0, l: 0 }
    if (!el) return ins
    const fr = el.getBoundingClientRect()
    const floating = (sel: string) => {
      const n = document.querySelector(sel)
      return n && getComputedStyle(n).position === 'absolute' ? n.getBoundingClientRect() : null
    }
    const top = floating('.topbar')
    const left = floating('.register')
    const right = floating('.inspector')
    const hud = el.querySelector('.hud-tools')?.getBoundingClientRect()
    if (top) ins.t = top.bottom - fr.top
    if (left) ins.l = left.right - fr.left
    if (right) ins.r = fr.right - right.left
    if (hud) ins.b = fr.bottom - hud.top
    return ins
  }, [])

  const fit = useCallback(() => {
    const el = frame.current
    if (!el || !aspect) return
    const ins = insets()
    const pad = 24
    const w = el.clientWidth - ins.l - ins.r - pad * 2
    const h = el.clientHeight - ins.t - ins.b - pad * 2
    const k = Math.max(MIN_ZOOM, Math.min(w / BASE_W, h / (BASE_W * aspect)))
    setView({
      k,
      x: ins.l + (el.clientWidth - ins.l - ins.r - BASE_W * k) / 2,
      y: ins.t + (el.clientHeight - ins.t - ins.b - BASE_W * aspect * k) / 2,
    })
  }, [aspect, insets])

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
      if (selectionStart.current) return
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
    const ins = insets()
    const mx = ins.l + (el.clientWidth - ins.l - ins.r) / 2
    const my = ins.t + (el.clientHeight - ins.t - ins.b) / 2
    setView((v) => {
      const k = clamp(v.k * f, MIN_ZOOM, MAX_ZOOM)
      return { k, x: mx - ((mx - v.x) * k) / v.k, y: my - ((my - v.y) * k) / v.k }
    })
  }

  const sheetPoint = (e: React.PointerEvent): Pt | null => {
    const el = frame.current
    if (!el || !aspect) return null
    const r = el.getBoundingClientRect()
    return [(e.clientX - r.left - view.x) / view.k / BASE_W,
      (e.clientY - r.top - view.y) / view.k / H]
  }

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as Element).closest('.hud') || state !== 'ready') return
    if (selectingRegion) {
      const point = sheetPoint(e)
      if (!point || point.some((value) => value < 0 || value > 1)) return
      e.preventDefault()
      e.currentTarget.setPointerCapture(e.pointerId)
      selectionStart.current = point
      setDraft(null)
      setSelectionHint(null)
      return
    }
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
    setDragging(true)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const el = frame.current
    if (!el) return
    const point = sheetPoint(e)
    if (selectionStart.current && selectingRegion && point) {
      setDraft(regionFromPoints(selectionStart.current, point))
    }
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
  const onPointerUp = (e: React.PointerEvent) => {
    if (selectionStart.current && selectingRegion) {
      const point = sheetPoint(e)
      if (point) {
        const next = regionFromPoints(selectionStart.current, point)
        const [x0, y0, x1, y1] = next.bbox
        if ((x1 - x0) * BASE_W * view.k >= 6 && (y1 - y0) * H * view.k >= 6) {
          onRegionChange(next)
        } else {
          setSelectionHint('Drag a larger box to select a region.')
        }
      }
    }
    selectionStart.current = null
    setDraft(null)
    drag.current = null
    setDragging(false)
  }

  const cancelPointer = () => {
    selectionStart.current = null
    setDraft(null)
    drag.current = null
    setDragging(false)
  }

  const visible = evidence.map((e, i) => ({ e, i })).filter(({ e }) => (e.page ?? 0) === page)
  const shownRegion = selectingRegion && draft ? draft : region

  return (
    <div
      ref={frame}
      className={`viewer-frame${dragging ? ' dragging' : ''}${selectingRegion ? ' selecting-region' : ''}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={cancelPointer}
      onPointerLeave={() => setCursor(null)}
      onDoubleClick={(e) => !selectingRegion && !(e.target as Element).closest('.hud') && fit()}
    >
      {src && (
        <div
          className="sheet"
          style={{
            width: BASE_W,
            height: H || undefined,
            transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.k})`,
            visibility: state === 'ready' ? 'visible' : 'hidden',
          }}
        >
          <img
            key={src}
            src={src}
            alt="Drawing sheet"
            draggable={false}
            decoding="async"
            onLoad={(e) => {
              const img = e.currentTarget
              setLoaded({ src: src!, aspect: img.naturalWidth ? img.naturalHeight / img.naturalWidth : 1 })
            }}
            onError={() => setFailed(src)}
          />
          {aspect && shownRegion && (
            <svg className="region-overlay" viewBox={`0 0 ${BASE_W} ${H}`} width={BASE_W} height={H} aria-hidden="true">
              <path fillRule="evenodd" className="region-shade" d={regionShade(shownRegion, BASE_W, H)} />
              <rect className="region-outline"
                x={shownRegion.bbox[0] * BASE_W} y={shownRegion.bbox[1] * H}
                width={(shownRegion.bbox[2] - shownRegion.bbox[0]) * BASE_W}
                height={(shownRegion.bbox[3] - shownRegion.bbox[1]) * H}
                strokeWidth={2 / view.k} />
            </svg>
          )}
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

      <div className="viewer-empty">
        {!src && <span>Choose a drawing to begin.</span>}
        {src && state === 'loading' && <span className="muted">Loading drawing…</span>}
        {src && state === 'error' && (
          <span>
            This drawing couldn’t be loaded.
            <br />
            <span className="muted">Check that the backend is running and the file is available.</span>
          </span>
        )}
      </div>

      <div className="hud hud-status glass">
        {selectingRegion && <span className="selection-instruction">{selectionHint ?? 'Drag on the plan to select a region · Esc to cancel'}</span>}
        <span className="mono">{cursor ? `${cursor[0].toFixed(3)}, ${cursor[1].toFixed(3)}` : '–, –'}</span>
        {renderNote && <span className="render-note">{renderNote}</span>}
      </div>

      <div className="hud hud-tools glass" role="toolbar" aria-label="View">
        <button className="hud-btn" onClick={() => zoomBy(1 / 1.25)} aria-label="Zoom out" title="Zoom out">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
            <path d="M3 8h10" />
          </svg>
        </button>
        <span className="zoom-readout">{Math.round(view.k * 100)}%</span>
        <button className="hud-btn" onClick={() => zoomBy(1.25)} aria-label="Zoom in" title="Zoom in">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
            <path d="M3 8h10M8 3v10" />
          </svg>
        </button>
        <button className="hud-btn text" onClick={fit} title="Fit drawing to window">
          Fit
        </button>
        <span className="hud-sep" aria-hidden />
        <button className={`hud-btn text region-toggle${selectingRegion ? ' active' : ''}`}
          disabled={state !== 'ready'} aria-pressed={selectingRegion}
          onClick={() => { cancelPointer(); setSelectionHint(null); onSelectionModeChange(!selectingRegion) }}
          title="Draw a box to ask about one part of the plan">
          {selectingRegion ? 'Cancel' : region ? 'Redraw region' : 'Draw region'}
        </button>
        {region && <button className="hud-btn text" onClick={() => { cancelPointer(); onRegionChange(null) }}>Clear</button>}
        <span className="hud-sep" aria-hidden />
        <label className="switch">
          <input type="checkbox" checked={showEvidence} onChange={(e) => setShowEvidence(e.target.checked)} />
          <span className="switch-track" aria-hidden />
          <span>Evidence</span>
          <span className="switch-count">{visible.length}</span>
        </label>
      </div>
    </div>
  )
}

function regionFromPoints(a: Pt, b: Pt): Region {
  const x = clamp(b[0], 0, 1)
  const y = clamp(b[1], 0, 1)
  return { bbox: [Math.min(a[0], x), Math.min(a[1], y), Math.max(a[0], x), Math.max(a[1], y)], page: 0 }
}

function regionShade(region: Region, w: number, h: number) {
  const [x0, y0, x1, y1] = region.bbox
  return `M0 0H${w}V${h}H0Z M${x0 * w} ${y0 * h}H${x1 * w}V${y1 * h}H${x0 * w}Z`
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
