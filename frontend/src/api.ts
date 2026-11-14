import type { Answer, AskRequest, Feedback, PickerQuestion } from "./types";
import { mockAsk } from "./mock";

// data/ is gitignored (dataset licence), so these files may be missing on a fresh clone.
// A glob that matches nothing yields {} and the picker is just empty, instead of a build error.
const splits = import.meta.glob<string>("../../data/splits/{demo,judge}_questions.jsonl", {
  query: "?raw",
  import: "default",
  eager: true,
});
const demoRaw = splits["../../data/splits/demo_questions.jsonl"] ?? "";
const judgeRaw = splits["../../data/splits/judge_questions.jsonl"] ?? "";

/** Harry's API (C5). Empty = built-in mock that follows C2, with drawings served by the Vite dev server. */
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
export const USING_MOCK = API_BASE === "";

function encodePath(p: string): string {
  return p.split("/").map(encodeURIComponent).join("/");
}

export function drawingImageUrl(path: string): string {
  return `${API_BASE}/drawing/${encodePath(path)}/image`;
}

export async function ask(req: AskRequest, signal?: AbortSignal): Promise<Answer> {
  if (USING_MOCK) return mockAsk(req);
  const model = req.model && req.model !== "auto" ? req.model : undefined;
  let res: Response;
  if (req.upload) {
    const form = new FormData();
    form.append("upload", req.upload);
    form.append("question", req.question);
    if (model) form.append("model", model);
    res = await fetch(`${API_BASE}/ask`, { method: "POST", body: form, signal });
  } else {
    res = await fetch(`${API_BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: req.path, question: req.question, ...(model ? { model } : {}) }),
      signal,
    });
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`The API answered ${res.status}. ${body.slice(0, 200)}`);
  }
  return (await res.json()) as Answer;
}

export async function sendFeedback(fb: Feedback): Promise<void> {
  if (USING_MOCK) {
    try {
      const log = JSON.parse(localStorage.getItem("bt.corrections") ?? "[]");
      log.push({ ...fb, at: new Date().toISOString() });
      localStorage.setItem("bt.corrections", JSON.stringify(log));
    } catch {
      /* storage blocked: the mock just drops it */
    }
    console.info("[mock] POST /feedback", fb);
    return;
  }
  const res = await fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fb),
  });
  if (!res.ok) throw new Error(`Saving the correction failed (${res.status}).`);
}

function parseJsonl(raw: string, set: "demo" | "judge"): PickerQuestion[] {
  return raw
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => ({ ...JSON.parse(l), set }));
}

export const DEMO_QUESTIONS = parseJsonl(demoRaw, "demo");
export const JUDGE_QUESTIONS = parseJsonl(judgeRaw, "judge");
export const ALL_QUESTIONS = [...DEMO_QUESTIONS, ...JUDGE_QUESTIONS];
