import type { Evidence, Pt, Region, Shape } from '../types'

/** SVG path for a shape in sheet pixels (w × h). Polygons keep their holes (even-odd). */
export function shapePath(shape: Shape, w: number, h: number): string {
  if (shape.kind === 'point') return ''
  if (shape.kind === 'bbox') {
    const [x0, y0, x1, y1] = shape.bbox
    return `M${x0 * w} ${y0 * h}H${x1 * w}V${y1 * h}H${x0 * w}Z`
  }
  return [shape.points, ...(shape.holes ?? [])]
    .map((ring) => ring.map(([x, y], i) => `${i ? 'L' : 'M'}${x * w} ${y * h}`).join('') + 'Z')
    .join('')
}

/** A representative point: the point itself, the box centre, or the polygon's vertex mean. */
export function shapeCentre(shape: Shape): Pt {
  if (shape.kind === 'point') return shape.point
  if (shape.kind === 'bbox') {
    const [x0, y0, x1, y1] = shape.bbox
    return [(x0 + x1) / 2, (y0 + y1) / 2]
  }
  const n = shape.points.length || 1
  const s = shape.points.reduce<Pt>((a, p) => [a[0] + p[0], a[1] + p[1]], [0, 0])
  return [s[0] / n, s[1] / n]
}

/** Top-left-most corner, for placing a number tag. */
export function shapeAnchor(shape: Shape): Pt {
  if (shape.kind === 'point') return shape.point
  if (shape.kind === 'bbox') return [shape.bbox[0], shape.bbox[1]]
  return shape.points.reduce((best, p) => (p[1] + p[0] * 0.25 < best[1] + best[0] * 0.25 ? p : best), shape.points[0])
}

export function regionPath(r: Region, w: number, h: number) {
  const [x0, y0, x1, y1] = r.bbox
  return `M${x0 * w} ${y0 * h}H${x1 * w}V${y1 * h}H${x0 * w}Z`
}

/**
 * Drawing-sheet zone grid. The long side gets 8 divisions; the short side is divided to keep the
 * cells near square. Columns are numbered left to right, rows lettered top to bottom, as on a
 * printed sheet border.
 */
export function zoneGrid(aspect: number): { cols: number; rows: number } {
  if (aspect <= 1) return { cols: 8, rows: Math.max(2, Math.round(8 * aspect)) }
  return { cols: Math.max(2, Math.round(8 / aspect)), rows: 8 }
}

const LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ' // no I or O, as on drawing borders

export function rowLetter(i: number) {
  return LETTERS[i] ?? String(i + 1)
}

export function zoneOf(p: Pt, aspect: number): string {
  const { cols, rows } = zoneGrid(aspect)
  const c = Math.min(cols - 1, Math.max(0, Math.floor(p[0] * cols)))
  const r = Math.min(rows - 1, Math.max(0, Math.floor(p[1] * rows)))
  return `${rowLetter(r)}${c + 1}`
}

export function evidenceZone(e: Evidence, aspect: number | null) {
  return aspect ? zoneOf(shapeCentre(e.shape), aspect) : null
}

/**
 * Revision-cloud outline around a box, in screen-sized scallops (`arc` px at zoom k). Drawn in
 * sheet pixels, so it scales with the sheet like the rest of the overlay.
 */
export function cloudPath(r: Region, w: number, h: number, k: number, arc = 16): string {
  const [x0, y0, x1, y1] = r.bbox.map((v, i) => v * (i % 2 ? h : w))
  const step = arc / k
  const edge = (ax: number, ay: number, bx: number, by: number) => {
    const len = Math.hypot(bx - ax, by - ay)
    const n = Math.max(1, Math.round(len / step))
    const rad = len / n / 1.7
    let d = ''
    for (let i = 1; i <= n; i++) {
      const px = ax + ((bx - ax) * i) / n
      const py = ay + ((by - ay) * i) / n
      d += `A${rad} ${rad} 0 0 1 ${px} ${py}`
    }
    return d
  }
  return `M${x0} ${y0}${edge(x0, y0, x1, y0)}${edge(x1, y0, x1, y1)}${edge(x1, y1, x0, y1)}${edge(x0, y1, x0, y0)}Z`
}
