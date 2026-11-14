// Pan, zoom, fit and region-drawing for a sheet that fills its container. No markup: each UI
// draws its own sheet, marks and controls from what this returns.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Pt, Region } from '../types'

export const BASE_W = 1000
const MIN_ZOOM = 0.05
const MAX_ZOOM = 14

export interface View { x: number; y: number; k: number }

interface Options {
  src: string | null
  pad: number
  selectingRegion: boolean
  onRegion: (r: Region) => void
  onSelectingChange: (active: boolean) => void
  /** Elements under the pointer that should not start a pan (toolbars on top of the sheet). */
  ignore?: string
}

export function useViewport({ src, pad, selectingRegion, onRegion, onSelectingChange, ignore = '[data-no-pan]' }: Options) {
  const frame = useRef<HTMLDivElement>(null)
  const [loaded, setLoaded] = useState<{ src: string; aspect: number } | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const aspect = loaded && loaded.src === src ? loaded.aspect : null
  const state: 'idle' | 'loading' | 'ready' | 'error' = !src ? 'idle' : aspect ? 'ready' : failed === src ? 'error' : 'loading'
  const H = aspect ? BASE_W * aspect : 0
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 })
  const [cursor, setCursor] = useState<Pt | null>(null)
  const [dragging, setDragging] = useState(false)
  const [draft, setDraft] = useState<Region | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 })
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null)
  const start = useRef<Pt | null>(null)

  const fit = useCallback(() => {
    const el = frame.current
    if (!el || !aspect) return
    const w = el.clientWidth - pad * 2
    const h = el.clientHeight - pad * 2
    const k = clamp(Math.min(w / BASE_W, h / (BASE_W * aspect)), MIN_ZOOM, MAX_ZOOM)
    setView({ k, x: (el.clientWidth - BASE_W * k) / 2, y: (el.clientHeight - BASE_W * aspect * k) / 2 })
  }, [aspect, pad])

  // Refit on every new image, even when two drawings share an aspect ratio.
  useLayoutEffect(() => { fit() }, [fit, loaded])

  useEffect(() => {
    const el = frame.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight })
      fit()
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [fit])

  useEffect(() => {
    const el = frame.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (start.current) return
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

  useEffect(() => {
    if (!selectingRegion) return
    const esc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      start.current = null
      setDraft(null)
      setHint(null)
      onSelectingChange(false)
    }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [selectingRegion, onSelectingChange])

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

  /** Centre the view on a normalized sheet point without changing the zoom. */
  const centreOn = (p: Pt) => {
    const el = frame.current
    if (!el || !aspect) return
    setView((v) => ({ ...v, x: el.clientWidth / 2 - p[0] * BASE_W * v.k, y: el.clientHeight / 2 - p[1] * H * v.k }))
  }

  const toSheet = (e: { clientX: number; clientY: number }): Pt | null => {
    const el = frame.current
    if (!el || !aspect) return null
    const r = el.getBoundingClientRect()
    return [(e.clientX - r.left - view.x) / view.k / BASE_W, (e.clientY - r.top - view.y) / view.k / H]
  }

  const reset = () => {
    start.current = null
    drag.current = null
    setDraft(null)
    setDragging(false)
  }

  const handlers = {
    onPointerDown: (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.button !== 0 || (e.target as Element).closest(ignore) || state !== 'ready') return
      if (selectingRegion) {
        const p = toSheet(e)
        if (!p || p.some((v) => v < 0 || v > 1)) return
        e.preventDefault()
        e.currentTarget.setPointerCapture(e.pointerId)
        start.current = p
        setDraft(null)
        setHint(null)
        return
      }
      e.currentTarget.setPointerCapture(e.pointerId)
      drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }
      setDragging(true)
    },
    onPointerMove: (e: React.PointerEvent) => {
      const p = toSheet(e)
      if (start.current && selectingRegion && p) setDraft(regionFrom(start.current, p))
      if (drag.current) {
        const d = drag.current
        setView((v) => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y }))
      }
      setCursor(p && p[0] >= 0 && p[0] <= 1 && p[1] >= 0 && p[1] <= 1 ? p : null)
    },
    onPointerUp: (e: React.PointerEvent) => {
      if (start.current && selectingRegion) {
        const p = toSheet(e)
        if (p) {
          const next = regionFrom(start.current, p)
          const [x0, y0, x1, y1] = next.bbox
          if ((x1 - x0) * BASE_W * view.k >= 6 && (y1 - y0) * H * view.k >= 6) onRegion(next)
          else setHint('Drag a larger box.')
        }
      }
      reset()
    },
    onPointerCancel: reset,
    onPointerLeave: () => setCursor(null),
    onDoubleClick: (e: React.MouseEvent) => { if (!selectingRegion && !(e.target as Element).closest(ignore)) fit() },
  }

  const imgProps = {
    src: src ?? undefined,
    draggable: false,
    decoding: 'async' as const,
    onLoad: (e: React.SyntheticEvent<HTMLImageElement>) => {
      const img = e.currentTarget
      setLoaded({ src: src!, aspect: img.naturalWidth ? img.naturalHeight / img.naturalWidth : 1 })
    },
    onError: () => setFailed(src),
  }

  const sheetStyle: React.CSSProperties = {
    width: BASE_W,
    height: H || undefined,
    transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.k})`,
    visibility: state === 'ready' ? 'visible' : 'hidden',
  }

  return { frame, state, aspect, W: BASE_W, H, view, size, cursor, dragging, draft, hint, setHint, fit, zoomBy, centreOn, reset, handlers, imgProps, sheetStyle }
}

export type Viewport = ReturnType<typeof useViewport>

function regionFrom(a: Pt, b: Pt): Region {
  const x = clamp(b[0], 0, 1)
  const y = clamp(b[1], 0, 1)
  return { bbox: [Math.min(a[0], x), Math.min(a[1], y), Math.max(a[0], x), Math.max(a[1], y)], page: 0 }
}

export function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v))
}
