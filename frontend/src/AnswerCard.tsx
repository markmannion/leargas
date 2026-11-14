import type { Answer, XY } from "./types";

const SOURCE_TEXT: Record<string, string> = {
  dxf: "Exact, from the DXF drawing",
  ifc: "Exact, from the IFC model",
  pdf_text: "Read from the PDF's text",
  "gemma-ft": "Fine-tuned Gemma (raster)",
  "gemma-base": "Base Gemma (raster)",
};

export function sourceText(s: string): string {
  return SOURCE_TEXT[s] ?? s;
}

export function formatUnit(unit: string | null): string {
  if (!unit || unit === "count") return "";
  return { m2: "m²", m3: "m³", ft2: "ft²", m: "m" }[unit] ?? unit;
}

function formatValue(v: number | string | null): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString("en-GB") : v.toLocaleString("en-GB", { maximumFractionDigits: 2 });
  }
  return String(v);
}

interface Props {
  answer: Answer;
  question: string;
  gold?: number | string | null;
  rejected: Set<string>;
  added: XY[];
  feedbackState: "idle" | "saving" | "saved" | "error";
  onToggle: (id: string) => void;
  onHighlight: (id: string | null) => void;
  highlight: string | null;
  onResetCorrections: () => void;
}

export function AnswerCard({ answer, gold, rejected, added, feedbackState, onToggle, onHighlight, highlight, onResetCorrections }: Props) {
  const isCount = answer.type === "count" && typeof answer.answer === "number";
  const corrected = isCount && (rejected.size > 0 || added.length > 0);
  const correctedValue = isCount ? (answer.answer as number) - rejected.size + added.length : null;
  const unit = formatUnit(answer.unit);
  const conf = answer.confidence;
  const isText = typeof answer.answer === "string";

  return (
    <section className={`card${answer.cannot_verify ? " is-abstain" : ""}`} aria-live="polite">
      {answer.cannot_verify ? (
        <div className="figure-block">
          <div>
            <h2 className="abstain-title">Can't verify this from the drawing</h2>
            <p className="abstain-reason">{answer.reason || "No engine could map the question, and the model wasn't confident enough to answer."}</p>
          </div>
        </div>
      ) : (
        <div className="figure-block">
          {corrected ? (
            <p className="figure">
              <s className="figure-was" aria-label={`was ${answer.answer}`}>{formatValue(answer.answer)}</s>
              <span className="figure-arrow" aria-hidden="true">→</span>
              <span className="figure-now">{correctedValue}</span>
            </p>
          ) : (
            <p className={`figure${isText ? " is-text" : ""}`}>
              {formatValue(answer.answer)}
              {unit && <span className="figure-unit">{unit}</span>}
            </p>
          )}
          {corrected && (
            <p className="corrected-note">
              Corrected by you: {rejected.size > 0 && `${rejected.size} rejected`}
              {rejected.size > 0 && added.length > 0 && ", "}
              {added.length > 0 && `${added.length} added`}.{" "}
              <span className="fb-state">
                {feedbackState === "saving" && "Saving…"}
                {feedbackState === "saved" && "Saved as training feedback."}
                {feedbackState === "error" && "Couldn't save. It will retry with your next change."}
              </span>{" "}
              <button type="button" className="link" onClick={onResetCorrections}>Undo all</button>
            </p>
          )}
        </div>
      )}

      <dl className="facts">
        <div>
          <dt>Source</dt>
          <dd>
            <span className={`src src-${answer.source}`}>{sourceText(answer.source)}</span>
          </dd>
        </div>
        {conf !== null && conf !== undefined && (
          <div>
            <dt>Confidence</dt>
            <dd className="conf">
              <span className="conf-bar" aria-hidden="true"><span style={{ width: `${Math.round(conf * 100)}%` }} /></span>
              {Math.round(conf * 100)}%
            </dd>
          </div>
        )}
        {answer.reason && !answer.cannot_verify && (
          <div>
            <dt>How</dt>
            <dd>{answer.reason}</dd>
          </div>
        )}
        {answer.working && (
          <div>
            <dt>Working</dt>
            <dd className="working">{answer.working}</dd>
          </div>
        )}
        {answer.cross_check && (
          <div>
            <dt>Cross-check</dt>
            <dd className={answer.cross_check.agree ? "agree" : "disagree"}>
              {sourceText(answer.cross_check.source)} says {formatValue(answer.cross_check.answer)}.{" "}
              {answer.cross_check.agree ? "They agree." : "They disagree, so check the highlighted items."}
            </dd>
          </div>
        )}
        {answer.cost && (
          <div>
            <dt>Time and cost</dt>
            <dd>
              {(answer.cost.latency_ms / 1000).toFixed(answer.cost.latency_ms < 1000 ? 2 : 1)} s,{" "}
              {answer.cost.usd < 0.0001 ? "under $0.0001" : `$${answer.cost.usd.toFixed(4)}`}
            </dd>
          </div>
        )}
        {gold !== undefined && gold !== null && !answer.cannot_verify && (
          <div>
            <dt>Dataset answer</dt>
            <dd>
              {formatValue(gold)}
              {typeof gold === "number" && typeof answer.answer === "number" && (
                <span className={matches(answer, gold, correctedValue) ? " agree" : " disagree"}>
                  {matches(answer, gold, correctedValue) ? " (match)" : " (differs)"}
                </span>
              )}
            </dd>
          </div>
        )}
      </dl>

      {answer.evidence.length > 0 && (
        <div className="evidence">
          <h3>Evidence on the drawing</h3>
          <ol>
            {answer.evidence.map((e, i) => {
              const off = rejected.has(e.id);
              return (
                <li
                  key={e.id}
                  className={`${off ? "is-rejected" : ""}${highlight === e.id ? " is-hl" : ""}`}
                  onMouseEnter={() => onHighlight(e.id)}
                  onMouseLeave={() => onHighlight(null)}
                >
                  <span className="ev-num">{i + 1}</span>
                  <span className="ev-label">{e.label ?? e.id}</span>
                  {e.value != null && <span className="ev-value">{typeof e.value === "number" ? `${e.value.toFixed(2)} ${unit}` : e.value}</span>}
                  {isCount && (
                    <button type="button" className="link" onClick={() => onToggle(e.id)} onFocus={() => onHighlight(e.id)}>
                      {off ? "Restore" : "Reject"}
                    </button>
                  )}
                </li>
              );
            })}
            {added.map((_, j) => (
              <li key={`a${j}`} className="is-added">
                <span className="ev-num">{answer.evidence.length + j + 1}</span>
                <span className="ev-label">Added by you</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

function matches(a: Answer, gold: number, corrected: number | null): boolean {
  const v = corrected ?? (a.answer as number);
  if (a.type === "count") return v === gold;
  return Math.abs(v - gold) <= 0.02 * Math.abs(gold);
}
