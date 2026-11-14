// Contract C2 (answer schema) and C5 (HTTP API), as agreed in blueprint-trace-build-plan.md.

export type Source = "dxf" | "ifc" | "pdf_text" | "gemma-ft" | "gemma-base";
export type EvidenceKind = "polygon" | "bbox" | "point";

/** Coordinates are normalised 0-1 against the drawing image, [x, y]. */
export type XY = [number, number];

export interface Evidence {
  id: string;
  kind: EvidenceKind;
  /** point: [[x, y]]; bbox: [[x0, y0], [x1, y1]]; polygon: [[x, y], ...] */
  coords: XY[];
  label?: string | null;
  value?: number | string | null;
}

export interface Answer {
  answer_id: string;
  answer: number | string | null;
  unit: string | null;
  type: "count" | "area" | "length" | "volume" | "text" | "other" | string;
  source: Source | string;
  confidence: number | null;
  cannot_verify: boolean;
  reason?: string | null;
  working?: string | null;
  evidence: Evidence[];
  cross_check?: { source: string; answer: number | string | null; agree: boolean } | null;
  cost?: { latency_ms: number; usd: number } | null;
}

/** Model override for evals / the base-vs-fine-tuned toggle. undefined = let the router decide. */
export type ModelChoice = "auto" | "gemma-base" | "gemma-ft";

export interface AskRequest {
  path?: string;
  upload?: File;
  question: string;
  model?: ModelChoice;
}

export interface Feedback {
  answer_id: string;
  /** points the engineer added (missed items), normalised [x, y] */
  added: XY[];
  /** evidence ids the engineer rejected */
  removed: string[];
}

/** A row of data/splits/demo_questions.jsonl or judge_questions.jsonl. */
export interface PickerQuestion {
  id: string;
  path: string;
  question: string;
  answer: number | string | null;
  unit: string | null;
  type: string;
  source: string;
  lang?: string;
  expected?: "answer" | "cannot_verify";
  beat?: string | null;
  kind?: string;
  notes?: string;
  answer_check?: string;
  set: "demo" | "judge";
}
