import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Evidence, XY } from "./types";

interface Props {
  src: string | null;
  evidence: Evidence[];
  rejected: Set<string>;
  added: XY[];
  /** counts can be corrected: click a marker to reject it, click empty paper to add a missed item */
  editable: boolean;
  highlight: string | null;
  onHighlight: (id: string | null) => void;
  onToggle: (id: string) => void;
  onAdd: (xy: XY) => void;
  onRemoveAdded: (index: number) => void;
}

interface View {
  s: number;
  tx: number;
  ty: number;
}

const MARKER_PX = 12; // marker radius on screen, independent of zoom

export function centroid(e: Evidence): XY {
  if (e.kind === "point") return e.coords[0];
  if (e.kind === "bbox") return [(e.coords[0][0] + e.coords[1][0]) / 2, (e.coords[0][1] + e.coords[1][1]) / 2];
  // polygon area centroid, falling back to the vertex mean for degenerate shapes
  let a = 0, cx = 0, cy = 0;
  const c = e.coords;
  for (let i = 0; i < c.length; i++) {
    const [x0, y0] = c[i];
    const [x1, y1] = c[(i + 1) % c.length];
    const f = x0 * y1 - x1 * y0;
    a += f;
    cx += (x0 + x1) * f;
    cy += (y0 + y1) * f;
  }
  if (Math.abs(a) < 1e-9) {
    return [c.reduce((s, p) => s + p[0], 0) / c.length, c.reduce((s, p) => s + p[1], 0) / c.length];
  }
  return [cx / (3 * a), cy / (3 * a)];
}

export function Viewer(props: Props) {
  const { src, evidence, rejected, added, editable, highlight } = props;
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [view, setView] = useState<View>({ s: 1, tx: 0, ty: 0 });
  const [loadError, setLoadError] = useState(false);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);

  const fit = useCallback(() => {
    const el = box.current;
    if (!el || !size) return;
    const pad = 24;
    const s = Math.min((el.clientWidth - pad * 2) / size.w, (el.clientHeight - pad * 2) / size.h);
    setView({ s, tx: (el.clientWidth - size.w * s) / 2, ty: (el.clientHeight - size.h * s) / 2 });
  }, [size]);

  useLayoutEffect(fit, [fit]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => fit());
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);
  useEffect(() => {
    setSize(null);
    setLoadError(false);
  }, [src]);

  // wheel zoom around the cursor (non-passive so the page doesn't scroll)
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const r = el.getBoundingClientRect();
      const mx = ev.clientX - r.left;
      const my = ev.clientY - r.top;
      setView((v) => {
        const k = Math.exp(-ev.deltaY * 0.0015);
        const s = Math.min(Math.max(v.s * k, 0.05), 40);
        return { s, tx: mx - ((mx - v.tx) * s) / v.s, ty: my - ((my - v.ty) * s) / v.s };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const zoomBy = (k: number) => {
    const el = box.current;
    if (!el) return;
    const mx = el.clientWidth / 2;
    const my = el.clientHeight / 2;
    setView((v) => {
      const s = Math.min(Math.max(v.s * k, 0.05), 40);
      return { s, tx: mx - ((mx - v.tx) * s) / v.s, ty: my - ((my - v.ty) * s) / v.s };
    });
  };

  const onPointerDown = (ev: React.PointerEvent) => {
    if (ev.button !== 0) return;
    drag.current = { x: ev.clientX, y: ev.clientY, tx: view.tx, ty: view.ty, moved: false };
  };
  const onPointerMove = (ev: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = ev.clientX - d.x;
    const dy = ev.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) > 4) {
      d.moved = true;
      (ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId);
    }
    if (d.moved) setView((v) => ({ ...v, tx: d.tx + dx, ty: d.ty + dy }));
  };
  const onPointerUp = (ev: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved || !size) return;
    // a click, not a drag
    const target = ev.target as Element;
    const markerEl = target.closest("[data-ev]");
    const addedEl = target.closest("[data-added]");
    if (markerEl && editable) {
      props.onToggle(markerEl.getAttribute("data-ev")!);
      return;
    }
    if (addedEl) {
      props.onRemoveAdded(Number(addedEl.getAttribute("data-added")));
      return;
    }
    if (!editable) return;
    const r = box.current!.getBoundingClientRect();
    const x = (ev.clientX - r.left - view.tx) / view.s / size.w;
    const y = (ev.clientY - r.top - view.ty) / view.s / size.h;
    if (x >= 0 && x <= 1 && y >= 0 && y <= 1) props.onAdd([x, y]);
  };

  const W = size?.w ?? 1;
  const H = size?.h ?? 1;
  const u = MARKER_PX / view.s; // one marker radius, in image pixels
  const n = evidence.length;

  return (
    <div className="viewer">
      <div
        ref={box}
        className={`viewer-stage${editable ? " is-editable" : ""}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => props.onHighlight(null)}
      >
        {!src && <p className="viewer-empty">Pick a question or upload a drawing to start.</p>}
        {src && loadError && <p className="viewer-empty">The drawing image didn't load. Check that the API serves {src}.</p>}
        {src && (
          <div
            className="viewer-sheet"
            style={{
              width: W,
              height: H,
              transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.s})`,
              visibility: size ? "visible" : "hidden",
            }}
          >
            <img
              src={src}
              alt="Drawing"
              draggable={false}
              onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth || 1600, h: e.currentTarget.naturalHeight || 1130 })}
              onError={() => setLoadError(true)}
            />
            {size && (
              <svg className="overlay" viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
                {evidence.map((e) => {
                  const off = rejected.has(e.id);
                  const hl = highlight === e.id;
                  const cls = `ev ev-${e.kind}${off ? " is-rejected" : ""}${hl ? " is-hl" : ""}`;
                  if (e.kind === "polygon")
                    return <polygon key={e.id} className={cls} points={e.coords.map(([x, y]) => `${x * W},${y * H}`).join(" ")} />;
                  if (e.kind === "bbox") {
                    const [[x0, y0], [x1, y1]] = e.coords;
                    return <rect key={e.id} className={cls} x={x0 * W} y={y0 * H} width={(x1 - x0) * W} height={(y1 - y0) * H} />;
                  }
                  return null;
                })}
                {evidence.map((e, i) => {
                  const [cx, cy] = centroid(e);
                  const off = rejected.has(e.id);
                  const hl = highlight === e.id;
                  return (
                    <g
                      key={`m-${e.id}`}
                      data-ev={e.id}
                      className={`marker${off ? " is-rejected" : ""}${hl ? " is-hl" : ""}`}
                      transform={`translate(${cx * W} ${cy * H})`}
                      onPointerEnter={() => props.onHighlight(e.id)}
                    >
                      <title>{`${i + 1}. ${e.label ?? e.id}${e.value != null ? ` (${e.value})` : ""}${editable ? (off ? ". Click to restore" : ". Click to reject") : ""}`}</title>
                      <circle r={u * 1.6} className="hit" />
                      <circle r={u} className="dot" />
                      <text className="num" fontSize={u * 1.05} dy={u * 0.37}>{i + 1}</text>
                      {off && <line className="strike" x1={-u * 1.1} y1={u * 1.1} x2={u * 1.1} y2={-u * 1.1} />}
                    </g>
                  );
                })}
                {added.map(([x, y], j) => (
                  <g key={`a-${j}`} data-added={j} className="marker is-added" transform={`translate(${x * W} ${y * H})`}>
                    <title>{`Added by you (${n + j + 1}). Click to remove`}</title>
                    <circle r={u * 1.6} className="hit" />
                    <circle r={u} className="dot" />
                    <text className="num" fontSize={u * 1.05} dy={u * 0.37}>{n + j + 1}</text>
                  </g>
                ))}
              </svg>
            )}
          </div>
        )}
      </div>
      <div className="viewer-tools" role="toolbar" aria-label="Zoom">
        <button type="button" onClick={() => zoomBy(1.25)} aria-label="Zoom in">+</button>
        <button type="button" onClick={() => zoomBy(0.8)} aria-label="Zoom out">−</button>
        <button type="button" onClick={fit}>Fit</button>
      </div>
      {editable && (
        <p className="viewer-hint">Click a marker to reject it. Click the drawing to add an item the count missed.</p>
      )}
    </div>
  );
}
