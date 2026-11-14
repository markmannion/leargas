import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ALL_QUESTIONS, DEMO_QUESTIONS, JUDGE_QUESTIONS, USING_MOCK, ask, drawingImageUrl, sendFeedback } from "./api";
import { AnswerCard } from "./AnswerCard";
import { Viewer } from "./Viewer";
import type { Answer, ModelChoice, PickerQuestion, XY } from "./types";

const MODEL_OPTIONS: { value: ModelChoice; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "gemma-base", label: "Base Gemma" },
  { value: "gemma-ft", label: "Fine-tuned Gemma" },
];

function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}

function optionLabel(q: PickerQuestion): string {
  const beat = q.beat ? `Beat ${q.beat.replace("beat", "")}: ` : "";
  const text = q.question.length > 70 ? q.question.slice(0, 68) + "…" : q.question;
  return `${beat}${text} (${fileName(q.path)})`;
}

export default function App() {
  const [pickedId, setPickedId] = useState<string>("");
  const [path, setPath] = useState<string | null>(null);
  const [upload, setUpload] = useState<{ file: File; url: string } | null>(null);
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState<ModelChoice>("auto");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asked, setAsked] = useState<{ question: string; model: ModelChoice } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState<XY[]>([]);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [fbState, setFbState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const abort = useRef<AbortController | null>(null);

  const picked = ALL_QUESTIONS.find((q) => `${q.set}:${q.id}` === pickedId);
  const imgSrc = upload ? upload.url : path ? drawingImageUrl(path) : null;

  const run = useCallback(
    async (q: string, p: string | null, up: File | null, m: ModelChoice) => {
      if (!q.trim() || (!p && !up)) return;
      abort.current?.abort();
      const ctl = new AbortController();
      abort.current = ctl;
      setLoading(true);
      setError(null);
      setRejected(new Set());
      setAdded([]);
      setFbState("idle");
      try {
        const a = await ask({ path: p ?? undefined, upload: up ?? undefined, question: q.trim(), model: m }, ctl.signal);
        if (!ctl.signal.aborted) {
          setAnswer(a);
          setAsked({ question: q.trim(), model: m });
        }
      } catch (e) {
        if (!ctl.signal.aborted) {
          setAnswer(null);
          setError(e instanceof Error ? e.message : String(e));
        }
      } finally {
        if (!ctl.signal.aborted) setLoading(false);
      }
    },
    [],
  );

  const pick = (key: string) => {
    setPickedId(key);
    const q = ALL_QUESTIONS.find((x) => `${x.set}:${x.id}` === key);
    if (!q) return;
    if (upload) URL.revokeObjectURL(upload.url);
    setUpload(null);
    setPath(q.path);
    setQuestion(q.question);
    setAnswer(null);
    void run(q.question, q.path, null, model);
  };

  const onUpload = (file: File | undefined) => {
    if (!file) return;
    if (upload) URL.revokeObjectURL(upload.url);
    setUpload({ file, url: URL.createObjectURL(file) });
    setPath(null);
    setPickedId("");
    setAnswer(null);
  };

  const switchModel = (m: ModelChoice) => {
    setModel(m);
    if (answer || loading) void run(question, path, upload?.file ?? null, m);
  };

  // deep links for the demo: ?q=demo:demo_01&model=gemma-base
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const m = params.get("model") as ModelChoice | null;
    if (m && MODEL_OPTIONS.some((o) => o.value === m)) setModel(m);
    const q = params.get("q");
    if (q && ALL_QUESTIONS.some((x) => `${x.set}:${x.id}` === q)) {
      const item = ALL_QUESTIONS.find((x) => `${x.set}:${x.id}` === q)!;
      setPickedId(q);
      setPath(item.path);
      setQuestion(item.question);
      void run(item.question, item.path, null, m ?? "auto");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!pickedId) return;
    const url = new URL(window.location.href);
    url.searchParams.set("q", pickedId);
    if (model !== "auto") url.searchParams.set("model", model);
    else url.searchParams.delete("model");
    window.history.replaceState(null, "", url);
  }, [pickedId, model]);

  // every correction is sent as the full current state for this answer (idempotent on the server)
  useEffect(() => {
    if (!answer || (rejected.size === 0 && added.length === 0 && fbState === "idle")) return;
    setFbState("saving");
    const t = setTimeout(() => {
      sendFeedback({ answer_id: answer.answer_id, added, removed: [...rejected] })
        .then(() => setFbState("saved"))
        .catch(() => setFbState("error"));
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rejected, added]);

  const editable = !!answer && !answer.cannot_verify && answer.type === "count" && typeof answer.answer === "number";
  const toggle = (id: string) =>
    setRejected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const groups = useMemo(() => {
    const beats = DEMO_QUESTIONS.filter((q) => q.beat).sort((a, b) => (a.beat! < b.beat! ? -1 : 1));
    const bySource = new Map<string, PickerQuestion[]>();
    for (const q of DEMO_QUESTIONS.filter((q) => !q.beat)) {
      const k = q.expected === "cannot_verify" ? "Should abstain" : q.source;
      bySource.set(k, [...(bySource.get(k) ?? []), q]);
    }
    return { beats, bySource: [...bySource.entries()], judge: JUDGE_QUESTIONS };
  }, []);

  const stale = answer && asked && (asked.question !== question.trim() || asked.model !== model);

  return (
    <div className="app">
      <header className="bar">
        <div className="brand">
          <span className="wordmark">BlueprintTrace</span>
          <span className="tagline">Ask the drawing. See the proof.</span>
        </div>
        {USING_MOCK && <span className="mock-chip" title="Set VITE_API_BASE in .env to use Harry's API">Mock API</span>}
      </header>

      <main className="layout">
        <Viewer
          src={imgSrc}
          evidence={answer && !answer.cannot_verify ? answer.evidence : []}
          rejected={rejected}
          added={added}
          editable={editable}
          highlight={highlight}
          onHighlight={setHighlight}
          onToggle={toggle}
          onAdd={(xy) => setAdded((a) => [...a, xy])}
          onRemoveAdded={(i) => setAdded((a) => a.filter((_, j) => j !== i))}
        />

        <aside className="panel">
          <form
            className="ask"
            onSubmit={(e) => {
              e.preventDefault();
              void run(question, path, upload?.file ?? null, model);
            }}
          >
            <label className="field">
              <span className="field-label">Drawing and question</span>
              <select value={pickedId} onChange={(e) => pick(e.target.value)}>
                <option value="">{upload ? `Uploaded: ${upload.file.name}` : "Choose a prepared question…"}</option>
                <optgroup label="Demo script">
                  {groups.beats.map((q) => (
                    <option key={q.id} value={`demo:${q.id}`}>{optionLabel(q)}</option>
                  ))}
                </optgroup>
                {groups.bySource.map(([src, qs]) => (
                  <optgroup key={src} label={`Demo set: ${src}`}>
                    {qs.map((q) => (
                      <option key={q.id} value={`demo:${q.id}`}>{optionLabel(q)}</option>
                    ))}
                  </optgroup>
                ))}
                <optgroup label="Judge-style questions">
                  {groups.judge.map((q) => (
                    <option key={q.id} value={`judge:${q.id}`}>{optionLabel(q)}</option>
                  ))}
                </optgroup>
              </select>
            </label>

            <label className="upload">
              <input type="file" accept="image/png,image/jpeg,application/pdf" onChange={(e) => onUpload(e.target.files?.[0])} />
              <span>Upload your own drawing</span>
            </label>

            <label className="field">
              <span className="field-label">Question</span>
              <textarea
                rows={3}
                value={question}
                placeholder="How many windows are drawn on this floor plan?"
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void run(question, path, upload?.file ?? null, model);
                  }
                }}
              />
            </label>

            <div className="ask-row">
              <div className="seg" role="radiogroup" aria-label="Model for raster drawings">
                {MODEL_OPTIONS.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    role="radio"
                    aria-checked={model === o.value}
                    className={model === o.value ? "is-on" : ""}
                    onClick={() => switchModel(o.value)}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
              <button type="submit" className="primary" disabled={loading || !question.trim() || (!path && !upload)}>
                {loading ? "Asking…" : "Ask"}
              </button>
            </div>
          </form>

          {error && (
            <p className="error" role="alert">
              {error} Check that the API is running at the address in VITE_API_BASE.
            </p>
          )}
          {loading && !answer && <p className="pending">Reading the drawing…</p>}
          {answer && (
            <div className={stale || loading ? "is-stale" : ""}>
              <AnswerCard
                answer={answer}
                question={question}
                gold={picked && picked.path === path && picked.question === asked?.question ? picked.answer : undefined}
                rejected={rejected}
                added={added}
                feedbackState={fbState}
                onToggle={toggle}
                onHighlight={setHighlight}
                highlight={highlight}
                onResetCorrections={() => {
                  setRejected(new Set());
                  setAdded([]);
                }}
              />
            </div>
          )}
          {!answer && !loading && !error && (
            <p className="pending">
              Answers come from exact geometry when the drawing has a CAD or IFC twin, and from Gemma when it is only an image.
              Every number is shown on the drawing so you can check it.
            </p>
          )}
        </aside>
      </main>
    </div>
  );
}
