// Mock /ask that follows contract C2, used until Harry's API is live (VITE_API_BASE empty).
// Answers reuse the gold answers from the demo/judge sets so the screen looks plausible, and the
// evidence positions are synthetic (seeded, deterministic). It exists to exercise every rendering path:
// points, bboxes, polygons, numbered markers, working, cross-check disagreement and cannot_verify.
import type { Answer, AskRequest, Evidence, Source, XY } from "./types";
import { ALL_QUESTIONS } from "./api";

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

function rng(seed: number) {
  let a = seed || 1;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function sourceFor(path: string, model: AskRequest["model"]): Source {
  const src = path.split("/")[1] ?? "upload";
  if (src === "swiss_dwellings") return "dxf";
  if (src === "ifc_models" || src === "ifc_bench") return "ifc";
  if (src === "opening_design") return "pdf_text";
  if (model === "gemma-base" || model === "gemma-ft") return model;
  return src === "cubicasa5k" ? "gemma-ft" : "gemma-base";
}

/** The plan sits in a sub-rectangle of the sheet: swiss renders have a title block, CubiCasa fills the image. */
function planBox(path: string): [number, number, number, number] {
  if (path.includes("swiss_dwellings")) return [0.28, 0.08, 0.72, 0.78];
  if (path.includes("opening_design")) return [0.08, 0.1, 0.62, 0.85];
  return [0.12, 0.1, 0.88, 0.9];
}

function gridPoints(n: number, box: [number, number, number, number], r: () => number): XY[] {
  const [x0, y0, x1, y1] = box;
  const cols = Math.max(1, Math.ceil(Math.sqrt(n * ((x1 - x0) / (y1 - y0)))));
  const rows = Math.max(1, Math.ceil(n / cols));
  const cells = Array.from({ length: cols * rows }, (_, i) => i).sort(() => r() - 0.5).slice(0, n);
  return cells.map((c) => {
    const cx = c % cols;
    const cy = Math.floor(c / cols);
    return [
      x0 + ((cx + 0.25 + r() * 0.5) / cols) * (x1 - x0),
      y0 + ((cy + 0.25 + r() * 0.5) / rows) * (y1 - y0),
    ] as XY;
  });
}

const round2 = (x: number) => Math.round(x * 100) / 100;

export async function mockAsk(req: AskRequest): Promise<Answer> {
  const path = req.path ?? `upload/${req.upload?.name ?? "drawing.png"}`;
  const seed = hash(path + "|" + req.question + "|" + (req.model ?? "auto"));
  const r = rng(seed);
  const gold = ALL_QUESTIONS.find((q) => q.path === path && q.question === req.question);
  const source = sourceFor(path, req.model);
  const isModel = source === "gemma-ft" || source === "gemma-base";
  const latency = isModel ? 900 + Math.round(r() * 1600) : 90 + Math.round(r() * 120);
  await sleep(Math.min(latency, 1400));

  const base = {
    answer_id: `a_${seed.toString(16).slice(0, 6)}`,
    source,
    cost: { latency_ms: latency, usd: isModel ? round2(latency / 3.6e6 * 2.0 * 1e4) / 1e4 : 0.000002 },
  };

  const looksType = gold?.type ?? (/(area|m²|m2|fläche|surface|pinta-ala)/i.test(req.question) ? "area" : "count");
  if (gold?.expected === "cannot_verify" || (!gold && req.upload === undefined && /fire|year|architect|u-value/i.test(req.question))) {
    return {
      ...base, source: req.model === "gemma-ft" ? "gemma-ft" : "gemma-base",
      answer: null, unit: null, type: gold?.type === "unanswerable" ? "other" : looksType,
      confidence: round2(0.18 + r() * 0.2), cannot_verify: true,
      reason: gold ? gold.notes || gold.answer_check || "The drawing does not show this."
        : "Nothing on this drawing answers that question.",
      evidence: [], working: null, cross_check: null,
    };
  }

  const box = planBox(path);
  // ---------------------------------------------------------------- text (schedules, IFC free text)
  if (looksType === "text") {
    const y = box[1] + r() * (box[3] - box[1] - 0.04);
    return {
      ...base, answer: (gold?.answer as string) ?? "See highlighted row", unit: null, type: "text",
      confidence: 0.97, cannot_verify: false, reason: "Read from the schedule's embedded text",
      evidence: [{ id: "e1", kind: "bbox", coords: [[box[0], y], [box[2], y + 0.022]], label: "Schedule row", value: gold?.answer ?? null }],
      working: null, cross_check: null,
    };
  }

  // ---------------------------------------------------------------- areas: room polygons that sum up
  if (looksType === "area" || looksType === "length" || looksType === "volume") {
    const total = typeof gold?.answer === "number" ? gold.answer : round2(20 + r() * 120);
    const k = Math.min(6, Math.max(1, Math.round(total / 18)));
    const weights = Array.from({ length: k }, () => 0.5 + r());
    const wsum = weights.reduce((a, b) => a + b, 0);
    const vals = weights.map((w) => round2((w / wsum) * total));
    vals[k - 1] = round2(total - vals.slice(0, -1).reduce((a, b) => a + b, 0));
    const cols = Math.ceil(Math.sqrt(k));
    const rows = Math.ceil(k / cols);
    const [x0, y0, x1, y1] = box;
    const ev: Evidence[] = vals.map((v, i) => {
      const cx = i % cols, cy = Math.floor(i / cols);
      const w = (x1 - x0) / cols, h = (y1 - y0) / rows;
      const ax = x0 + cx * w + w * 0.06, ay = y0 + cy * h + h * 0.06, bx = ax + w * 0.88, by = ay + h * 0.88;
      const notch = 0.25 + r() * 0.3;
      return {
        id: `e${i + 1}`, kind: "polygon",
        coords: [[ax, ay], [bx, ay], [bx, ay + (by - ay) * notch], [ax + (bx - ax) * 0.7, ay + (by - ay) * notch], [ax + (bx - ax) * 0.7, by], [ax, by]],
        label: ["Zimmer", "Küche", "Bad", "Korridor", "Reduit", "Wohnen"][i % 6] + ` ${i + 1}`, value: v,
      };
    });
    const unit = gold?.unit ?? "m2";
    return {
      ...base, answer: total, unit, type: looksType, confidence: isModel ? round2(0.55 + r() * 0.3) : 0.99,
      cannot_verify: false,
      reason: source === "dxf" ? `Summed ${k} room polygons from the DXF (layer ROOM_OUTLINE)` : `Read ${k} printed room areas`,
      working: `${vals.map((v) => v.toFixed(2)).join(" + ")} = ${total.toFixed(2)}`,
      evidence: ev,
      cross_check: source === "dxf" ? { source: "gemma-ft", answer: round2(total * (r() < 0.7 ? 1 : 1.07)), agree: true } : null,
    };
  }

  // ---------------------------------------------------------------- counts
  let n = typeof gold?.answer === "number" ? gold.answer : 1 + Math.floor(r() * 8);
  if (source === "gemma-base" && gold) n = Math.max(0, n + (r() < 0.5 ? -1 : 1) * (1 + Math.floor(r() * 2)));
  const pts = gridPoints(n, box, r);
  const kind = source === "dxf" || source === "ifc" ? "bbox" : "point";
  const noun = /window|ikkun|fenster|fenêtre|fönster/i.test(req.question) ? "Window"
    : /door|ove|tür|porte/i.test(req.question) ? "Door"
    : /toilet|wc/i.test(req.question) ? "WC" : "Item";
  const ev: Evidence[] = pts.map((p, i) => ({
    id: `e${i + 1}`, kind,
    coords: kind === "bbox" ? [[p[0] - 0.012, p[1] - 0.008], [p[0] + 0.012, p[1] + 0.008]] : [p],
    label: `${noun} ${i + 1}`, value: null,
  }));
  const ccAnswer = source === "dxf" ? (r() < 0.75 ? n : n - 1) : null;
  return {
    ...base, answer: n, unit: "count", type: "count",
    confidence: isModel ? round2(source === "gemma-ft" ? 0.78 + r() * 0.2 : 0.4 + r() * 0.3) : 0.99,
    cannot_verify: false,
    reason: source === "dxf" ? `Counted entities on layer ${noun.toUpperCase()}`
      : source === "ifc" ? `Counted Ifc${noun} elements on this storey`
      : `${source === "gemma-ft" ? "Fine-tuned" : "Base"} Gemma counted ${n} and marked each one`,
    working: null,
    evidence: ev,
    cross_check: ccAnswer !== null ? { source: "gemma-ft", answer: ccAnswer, agree: ccAnswer === n } : null,
  };
}
