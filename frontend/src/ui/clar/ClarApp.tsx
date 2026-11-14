import { useEffect, useMemo, useRef, useState } from 'react'
import '@fontsource/barlow/400.css'
import '@fontsource/barlow/500.css'
import '@fontsource/barlow/600.css'
import '@fontsource/barlow/700.css'
import '@fontsource/barlow-semi-condensed/400.css'
import '@fontsource/barlow-semi-condensed/500.css'
import '@fontsource/barlow-semi-condensed/600.css'
import '@fontsource/barlow-semi-condensed/700.css'
import '@fontsource/barlow-condensed/500.css'
import '@fontsource/barlow-condensed/600.css'
import '@fontsource/barlow-condensed/700.css'
import './clar.css'
import { api } from '../../api'
import type { Answer, Drawing, Engine } from '../../types'
import { TYPE_LABEL } from '../../format'
import { useSession, type LogEntry, type Session } from '../../core/session'
import { useViewport } from '../../core/viewport'
import { collectionName, drawingName, FORMAT_LABEL, suggestionsFor, vectorTwins } from '../../core/catalogue'
import { explain, itemised, rejectedGuess, valueParts, value } from '../../core/explain'
import { evidenceZone, shapeCentre, zoneOf } from '../../core/shapes'
import { OpeningTable, RoomTable, SlabTable } from '../../core/breakdowns'
import { speakableAnswer, useVoiceInput } from '../../voice'
import { UPLOAD_ACCEPT, useUpload } from '../../core/upload'
import { answerCost, formatUsd } from '../../core/cost'
import { ClarSheet } from './ClarSheet'
import { ClarRegister } from './ClarRegister'
import { CrossCheck } from './CrossCheck'

const ENGINES: { id: Engine; label: string }[] = [
  { id: 'auto', label: 'Automatic' },
  { id: 'geometry', label: 'Geometry only' },
  { id: 'sheet', label: 'Sheet reader only' },
  { id: 'gemma_ft', label: 'Gemma, fine-tuned' },
  { id: 'gemma_base', label: 'Gemma, base' },
]

const STATUS: Record<Answer['status'], [string, string]> = {
  verified: ['Verified', 'One confident source, or two that agree.'],
  partial: ['Partial', 'Answered, but the evidence only partly supports it.'],
  disagreement: ['Disagreement', 'The engines gave different answers.'],
  cannot_verify: ['Cannot verify', 'Held back: no source was sure enough.'],
}

const RENDER_NOTE: Record<Drawing['render'], string | null> = {
  image: null,
  pdf: 'Page 1 of the PDF',
  dxf: 'Rendered from the DXF',
  none: 'An IFC model has no sheet to show. Questions still work.',
}

const ref = (id: number) => `Q${String(id).padStart(2, '0')}`

export default function ClarApp() {
  const s = useSession()
  const [registerOpen, setRegisterOpen] = useState(false)
  const [showMarks, setShowMarks] = useState(true)
  const up = useUpload((d) => s.uploaded(d))
  const [dropping, setDropping] = useState(false)
  const src = s.selected && s.selected.render !== 'none' ? api.drawingUrl(s.selected.path) : null
  const vp = useViewport({
    src, pad: 36, selectingRegion: s.selectingRegion,
    onRegion: s.changeRegion, onSelectingChange: s.setSelectingRegion,
  })
  const evidence = s.answer?.evidence ?? []
  const pick = (i: number) => {
    const e = evidence[i]
    if (!e) return
    s.setHovered(i)
    vp.centreOn(shapeCentre(e.shape))
  }

  // A new answer starts at the top of the strip, even if a suggestion far down was clicked.
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => { scroller.current?.scrollTo({ top: 0 }) }, [s.activeEntry, s.busy])

  const highlighted = s.answer?.room_areas?.find((r) => s.hovered !== null && r.evidence_indices.includes(s.hovered))?.evidence_indices

  return (
    <div className="clar">
      <main className={`cl-field${dropping ? ' is-dropping' : ''}`} aria-label="Sheet"
        onDragOver={(e) => {
          if (registerOpen || !e.dataTransfer.types.includes('Files')) return
          e.preventDefault()
          setDropping(true)
        }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropping(false) }}
        onDrop={(e) => {
          if (registerOpen || !e.dataTransfer.files.length) return
          e.preventDefault()
          setDropping(false)
          void up.upload(e.dataTransfer.files)
        }}>
        <ClarSheet vp={vp} evidence={evidence} showMarks={showMarks} hovered={s.hovered} highlighted={highlighted}
          onHover={s.setHovered} region={s.region} selecting={s.selectingRegion}
          renderNote={s.selected ? RENDER_NOTE[s.selected.render] : null} />
        <footer className="cs-block" data-no-pan aria-label="Title block">
          <div className="cs-f"><span className="cs-label">Zone</span><span>{vp.cursor && vp.aspect ? zoneOf(vp.cursor, vp.aspect) : '—'}</span></div>
          <div className="cs-f"><span className="cs-label">Zoom</span><span>{Math.round(vp.view.k * 100)}%</span></div>
          <div className="cs-f"><span className="cs-label">Format</span><span>{s.selected ? FORMAT_LABEL[s.selected.render] : '—'}</span></div>
          <div className="cs-f"><span className="cs-label">Ref.</span><span>{s.activeEntry ? ref(s.activeEntry) : '—'}</span></div>
          <label className="cs-f cs-f-wide">
            <span className="cs-label">Checked by</span>
            <select value={s.engine} onChange={(e) => s.setEngine(e.target.value as Engine)}
              title="Which engine answers. Automatic uses geometry when there is a DXF or IFC file, the sheet reader for large sheets, and otherwise the fine-tuned model.">
              {ENGINES.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
            </select>
          </label>
          <div className="cs-f"><span className="cs-label">Date</span><span>{today}</span></div>
          <div className="cs-f"><span className="cs-label">Sheet</span><span>{s.selected ? '1 of 1' : '—'}</span></div>
        </footer>
        {dropping && (
          <div className="cl-drop" aria-hidden="true">
            <p><strong>Drop to upload</strong>PDF, PNG, JPG, DXF or IFC</p>
          </div>
        )}
        {registerOpen && (
          <ClarRegister drawings={s.drawings} selected={s.selected?.path ?? null} loading={s.listLoading} error={s.listError}
            onSelect={(d) => { s.select(d); setRegisterOpen(false) }}
            onUploaded={(d) => { s.uploaded(d); setRegisterOpen(false) }}
            onClose={() => setRegisterOpen(false)} />
        )}
      </main>

      <aside className="cs" aria-label="Title strip">
        <header className="cs-head">
          <h1 className="cs-mark">Léargas</h1>
          <ModelStatus s={s} />
        </header>

        <section className="cs-cell cs-drawing">
          <span className="cs-label">Drawing</span>
          {s.selected ? <DrawingTitle d={s.selected} /> : <p className="cs-title">{s.listLoading ? 'Loading the register…' : 'None open'}</p>}
          <button type="button" className="cs-link" onClick={() => setRegisterOpen((o) => !o)} aria-expanded={registerOpen}>
            {registerOpen ? 'Close the register' : 'Drawing register'}
          </button>
          <UploadControl up={up} />
        </section>

        <AskCell s={s} key={s.selected?.path ?? 'none'} />

        <div className="cs-scroll" ref={scroller}>
          {s.askError && <p className="cs-error"><strong>The request failed.</strong> {s.askError}</p>}
          {s.busy && s.pending && (
            <div className="cs-pending" role="status">
              <span className="cs-label">{ref(s.log.length + 1)} · asking</span>
              <p>{s.pending}</p>
            </div>
          )}
          {s.answer && !s.busy && (
            <AnswerCell s={s} answer={s.answer} aspect={vp.aspect} showMarks={showMarks} setShowMarks={setShowMarks} onPick={pick} />
          )}
          <Suggestions s={s} />
          <LogCell log={s.log} active={s.activeEntry} onOpen={s.reopen} />
        </div>

      </aside>
    </div>
  )
}

/** Upload your own drawing: the main way in for a new sheet, so it sits under the drawing title. */
function UploadControl({ up }: { up: ReturnType<typeof useUpload> }) {
  const file = useRef<HTMLInputElement>(null)
  const note = up.error ?? (up.message || 'PDF, PNG, JPG, DXF or IFC')
  return (
    <div className="cs-upload">
      <input ref={file} type="file" hidden multiple accept={UPLOAD_ACCEPT}
        onChange={(e) => { void up.upload(e.currentTarget.files); e.currentTarget.value = '' }} />
      <button type="button" className="cs-up" disabled={up.busy} onClick={() => file.current?.click()}>
        <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
          <path d="M8 11V2.5M4.5 6 8 2.5 11.5 6M2.5 10.5v3h11v-3" fill="none" stroke="currentColor" strokeWidth="1.6" />
        </svg>
        {up.busy ? (up.progress === 100 ? 'Preparing…' : `Uploading ${up.progress}%`) : 'Upload a drawing'}
      </button>
      <p className={`cs-up-note${up.error ? ' is-error' : ''}`} role="status">{note}</p>
    </div>
  )
}

const today = new Date().toLocaleDateString('en-IE', { day: '2-digit', month: '2-digit', year: 'numeric' }).replace(/\//g, '.')

// Speech is louder than this on the meter's 0-1 scale; quieter is room noise.
const HEARING = 0.2

/** Live bars that move with the microphone, so you can see it is hearing you. */
function VoiceMeter({ level }: { level: number }) {
  const hearing = level >= HEARING
  return (
    <span className={`vm${hearing ? ' is-hearing' : ''}`} role="status">
      <span className="vm-bars" aria-hidden="true">
        {[0.55, 0.85, 1, 0.85, 0.55].map((w, i) => (
          <i key={i} style={{ transform: `scaleY(${Math.max(0.18, Math.min(1, level * 1.6 * w))})` }} />
        ))}
      </span>
      {hearing ? 'Hearing you' : 'Listening…'} · Stop when done
    </span>
  )
}

type Light = 'ready' | 'down' | 'checking' | 'off' | 'mock'

const LIGHT_WORD: Record<Light, string> = { ready: 'Ready', down: 'Offline', checking: 'Checking', off: 'Not set up', mock: 'Mock' }

function gemmaLight(st: string | undefined, backend: Session['connection']): Light {
  if (backend === 'offline') return 'down'
  if (backend === 'connecting') return 'checking'
  if (backend === 'mock') return 'mock'
  if (st === 'available') return 'ready'
  if (st === 'checking') return 'checking'
  if (st === 'unconfigured' || st === 'disabled') return 'off'
  return 'down'
}

/** One status light per model, in its cross-check colour. Models the current setting won't use are dimmed. */
function ModelStatus({ s }: { s: Session }) {
  const models = s.health?.gemma_status?.models ?? {}
  const geo: Light = s.connection === 'offline' ? 'down' : s.connection === 'connecting' ? 'checking' : s.connection === 'mock' ? 'mock' : 'ready'
  const rows: { id: string; lane: 'measure' | 'model'; name: string; light: Light; used: boolean; about: string }[] = [
    { id: 'geo', lane: 'measure', name: 'Geometry', light: geo, used: s.engine !== 'gemma_ft' && s.engine !== 'gemma_base',
      about: 'Measures DXF and IFC files, and reads the text and lines on large sheets.' },
    { id: 'ft', lane: 'model', name: 'Gemma FT', light: gemmaLight(models['gemma-ft'] ?? s.health?.gemma_status?.status, s.connection),
      used: s.engine === 'auto' || s.engine === 'gemma_ft', about: 'Fine-tuned Gemma, which reads the drawing image.' },
    { id: 'base', lane: 'model', name: 'Gemma base', light: gemmaLight(models['gemma-base'] ?? s.health?.gemma_status?.status, s.connection),
      used: s.engine === 'gemma_base', about: 'Base Gemma, before fine-tuning.' },
  ]
  const title = s.health ? `${s.health.gold_questions_loaded.toLocaleString()} reference questions loaded` : undefined
  if (rows.every((r) => r.light === 'ready' || !r.used)) {
    const detail = rows.map((r) => `${r.name}: ${LIGHT_WORD[r.light]}${r.used ? '' : ' (not used by this setting)'}`).join('\n')
    return (
      <p className="ms-ok" role="status" title={title ? `${detail}\n${title}` : detail}>
        {rows.filter((r) => r.used).map((r) => <i key={r.id} className={`ms-light is-${r.lane}`} aria-hidden="true" />)}
        All checks ready
      </p>
    )
  }
  return (
    <ul className="ms" role="status" aria-label="Model status" title={title}>
      {rows.map((r) => (
        <li key={r.id} className={`ms-row is-${r.lane} is-${r.light}${r.used ? ' is-used' : ''}`}
          title={`${r.about} ${LIGHT_WORD[r.light]}.${r.used ? '' : ' Not used by the current setting.'}`}>
          <i className="ms-light" aria-hidden="true" />
          <span className="ms-name">{r.name}</span>
          <span className="ms-word">{LIGHT_WORD[r.light]}</span>
        </li>
      ))}
    </ul>
  )
}

function DrawingTitle({ d }: { d: Drawing }) {
  const [main, sub] = drawingName(d.name)
  const twins = vectorTwins(d)
  const meta = [sub, d.collection === 'uploads' ? '' : collectionName(d.collection)].filter(Boolean).join(' · ')
  const checked = twins.length > 0 && d.render !== 'dxf' && d.render !== 'none'
  return (
    <>
      <p className="cs-title" title={d.path}>{main}</p>
      {(meta || checked) && <p className="cs-sub">
        {meta}{checked && <>{meta ? ' · ' : ''}checked against {twins.join(' + ')}</>}
      </p>}
    </>
  )
}

function AskCell({ s }: { s: Session }) {
  const [text, setText] = useState('')
  const box = useRef<HTMLTextAreaElement>(null)
  const d = s.selected
  const blocked = !d || s.busy || s.selectingRegion
  const submit = (q: string, spoken = false) => {
    const t = q.trim()
    if (!t || blocked) return
    setText(t)
    void s.ask(t, { spoken })
  }
  const mic = useVoiceInput((t) => submit(t, true))
  const listening = mic.state === 'recording'

  // "/" puts the cursor in the question box, as in a search field.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === '/' && !(e.target as Element).closest('input, textarea, select')) { e.preventDefault(); box.current?.focus() }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])

  const [more, setMore] = useState(false)
  const clouding = Boolean(s.region) || s.selectingRegion

  return (
    <section className="cs-cell cs-ask">
      <form onSubmit={(e) => { e.preventDefault(); submit(text) }}>
        <div className={`cs-q${listening ? ' is-listening' : ''}${listening && mic.level >= HEARING ? ' is-hearing' : ''}${!d ? ' is-off' : ''}`}
          style={listening ? ({ '--lvl': mic.level } as React.CSSProperties) : undefined} onClick={() => box.current?.focus()}>
          <textarea id="cl-q" ref={box} rows={2} aria-label="Ask a question (press / to jump here)" value={text} disabled={!d}
            placeholder={!d ? 'Open a drawing first'
              : listening ? 'Listening… speak your question'
                : mic.state === 'transcribing' ? 'Writing it down…'
                  : s.region ? 'Ask in any language, e.g. How many doors are inside the cloud?' : 'Ask in any language, e.g. How many windows are on this floor?'}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(text) } }} />
          <div className="cs-q-bar">
            {s.voice && (
              <button type="button" className={`cs-mic is-${mic.state}`} onClick={(e) => { e.stopPropagation(); mic.toggle() }}
                aria-pressed={listening} disabled={blocked || mic.state === 'transcribing'}
                title={listening ? 'Stop and ask' : 'Ask by speaking, in any language'}>
                <MicIcon />
                {listening ? 'Stop' : mic.state === 'transcribing' ? 'Writing…' : 'Speak'}
              </button>
            )}
            <span className="cs-q-hint">
              {mic.error ? <span className="cs-warn">{mic.error}</span>
                : listening ? <VoiceMeter level={mic.level} />
                  : null}
            </span>
            <button type="submit" className="cs-btn cs-go" disabled={blocked || !text.trim()}>{s.busy ? 'Asking…' : 'Ask'}</button>
          </div>
        </div>
      </form>

      <details className="cs-more" open={more || clouding} onToggle={(e) => setMore(e.currentTarget.open)}>
        <summary>More ways to ask</summary>
        <div className="cs-scope" role="group" aria-label="What to ask about">
          <span className="cs-more-k">Ask about</span>
          <button type="button" aria-pressed={!s.region && !s.selectingRegion} disabled={!d}
            onClick={() => { if (s.selectingRegion) s.setSelectingRegion(false); if (s.region) s.changeRegion(null) }}>Whole sheet</button>
          <button type="button" aria-pressed={Boolean(s.region) || s.selectingRegion} disabled={!d || d.render === 'none'}
            onClick={() => s.setSelectingRegion(!s.selectingRegion)}>
            {s.selectingRegion ? 'Cancel cloud' : s.region ? 'Redraw cloud' : 'Cloud a region'}
          </button>
        </div>
        <div className="cs-takeoff">
          <span className="cs-more-k">Takeoff</span>
          <button type="button" className="cs-btn" disabled={blocked}
            onClick={() => { setText('Show floor areas by room'); void s.ask('Show floor areas by room', { floorAreas: true }) }}>
            {s.region && s.areaMode === 'intersection' ? 'Floor area in cloud' : 'Room areas'}
          </button>
          <button type="button" className="cs-btn" disabled={blocked || Boolean(s.region)}
            title={s.region ? 'Slab areas use the whole sheet' : 'Slab area grouped by thickness and bars'}
            onClick={() => submit('Slab area by type (thickness and bars)')}>Slab areas</button>
        </div>
        {s.region && (
          <fieldset className="cs-mode">
            <legend className="cs-label">Area in the cloud</legend>
            <label><input type="radio" name="cl-mode" checked={s.areaMode === 'whole_rooms'} onChange={() => s.changeAreaMode('whole_rooms')} /> Whole rooms</label>
            <label><input type="radio" name="cl-mode" checked={s.areaMode === 'intersection'} onChange={() => s.changeAreaMode('intersection')} /> Exact cut</label>
          </fieldset>
        )}
      </details>
    </section>
  )
}

function AnswerCell({ s, answer: a, aspect, showMarks, setShowMarks, onPick }: {
  s: Session
  answer: Answer
  aspect: number | null
  showMarks: boolean
  setShowMarks: (v: boolean) => void
  onPick: (i: number) => void
}) {
  const [num, unit] = valueParts(a)
  const cv = a.status === 'cannot_verify'
  const guess = rejectedGuess(a)
  const notes = explain(a, s.reference)
  const linked = { answer: a, hovered: s.hovered, onHover: s.setHovered, onPick }
  const longText = typeof a.answer === 'string' && a.answer.length > 14
  const sp = s.speaker
  const cost = answerCost(a)

  return (
    <article className={`ca is-${a.status}`} aria-live="polite">
      <div className="ca-meta">
        <span className="cs-label">{s.activeEntry ? ref(s.activeEntry) : 'Answer'} · {TYPE_LABEL[a.type]}{a.region ? ' · in cloud' : ''}</span>
        {a.latency_ms != null && <span className="ca-ms">{a.latency_ms < 1000 ? `${Math.max(1, Math.round(a.latency_ms))} ms` : `${(a.latency_ms / 1000).toFixed(1)} s`}</span>}
        {cost && <span className="ca-ms ca-cost" title={`Estimated compute cost of 1,000 answers like this one. ${cost.note}`}>≈ {formatUsd(cost.per1k)} per 1,000</span>}
        {s.voice && (
          <button type="button" className="cs-link" onClick={() => (sp.speaking ? sp.stop() : void sp.speak(speakableAnswer(a)))}
            title={sp.error ?? undefined}>{sp.speaking ? 'Stop reading' : 'Read aloud'}</button>
        )}
      </div>
      <p className="ca-q">{a.question}</p>
      <CrossCheck answer={a} engine={s.engine} gemma={s.gemmaState}>
        <div className={`ca-row${longText ? ' is-text' : ''}`}>
          <p className={`ca-value${longText ? ' is-text' : ''}`}>
            <span className="cs-label ca-result">Result</span>
            {cv ? <span className="ca-num">—</span> : <><span className="ca-num">{num}</span>{unit && <span className="ca-unit">{unit}</span>}</>}
          </p>
          <div className="ca-status">
            <strong>{STATUS[a.status][0]}</strong>
            <span>{guess ? 'Guess held back' : STATUS[a.status][1]}</span>
          </div>
        </div>
      </CrossCheck>

      <ol className="ca-notes">{notes.map((n, i) => <li key={i}>{n}</li>)}</ol>
      {a.explanation && <p className="ca-expl">{a.explanation}</p>}

      <RoomTable {...linked} />
      <SlabTable {...linked} />
      <OpeningTable {...linked} />

      {a.evidence.length > 0 && !itemised(a) && (
        <table className="bd bd-evidence">
          <caption>Marks on the sheet</caption>
          <thead><tr><th scope="col" className="n">No.</th><th scope="col">Item</th><th scope="col">Zone</th>{a.evidence.some((e) => e.value != null) && <th scope="col" className="n">Value</th>}</tr></thead>
          <tbody>
            {a.evidence.map((e, i) => (
              <tr key={i} className={s.hovered === i ? 'is-on' : undefined} data-linked=""
                onPointerEnter={() => s.setHovered(i)} onPointerLeave={() => s.setHovered(null)} onClick={() => onPick(i)}>
                <th scope="row" className="n">{i + 1}</th>
                <td>{e.label ?? (e.shape.kind === 'point' ? 'Point' : e.shape.kind === 'bbox' ? 'Box' : 'Outline')}{e.page > 0 && ` · p${e.page + 1}`}</td>
                <td>{evidenceZone(e, aspect) ?? '—'}</td>
                {a.evidence.some((x) => x.value != null) && <td className="n">{e.value != null ? value({ ...a, answer: e.value }) : ''}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {a.evidence.length > 0 && (
        <label className="ca-toggle">
          <input type="checkbox" checked={showMarks} onChange={(e) => setShowMarks(e.target.checked)} />
          Show the {a.evidence.length} {a.evidence.length === 1 ? 'mark' : 'marks'} on the sheet
          <span className="ca-key" aria-hidden="true"><i className="k-geo" />measured <i className="k-read" />read <i className="k-est" />Gemma</span>
        </label>
      )}
    </article>
  )
}

function Suggestions({ s }: { s: Session }) {
  const all = useMemo(() => suggestionsFor(s.selected), [s.selected])
  const [lang, setLang] = useState('all')
  const langs = useMemo(() => [...new Set(all.map((q) => q.lang))].sort(), [all])
  const [everything, setEverything] = useState(false)
  const filtered = lang === 'all' || !langs.includes(lang) ? all : all.filter((q) => q.lang === lang)
  const shown = everything ? filtered : filtered.slice(0, 3)
  if (!all.length) return null
  const fromDataset = all[0].fromDataset
  return (
    <details className="cq" open={!s.answer}>
      <summary>
        <span className="cs-label">{fromDataset ? 'Questions on file' : 'Questions to try'}</span>
        <span className="cq-n">{filtered.length}</span>
      </summary>
      {langs.length > 1 && (
        <div className="cq-langs" role="group" aria-label="Language">
          {['all', ...langs].map((l) => (
            <button key={l} type="button" aria-pressed={lang === l} onClick={() => setLang(l)}>{l === 'all' ? 'All' : l}</button>
          ))}
        </div>
      )}
      <ol>
        {shown.map((q, i) => (
          <li key={i}>
            <button type="button" disabled={s.busy || s.selectingRegion || !s.selected}
              onClick={() => void s.ask(q.question)}
              title={q.weak ? 'The model rarely counts doors and windows right from the image alone, so it will usually hold the answer back.' : undefined}>
              <span>{q.question}</span>
              {q.weak && <small>The model is often wrong on these</small>}
            </button>
          </li>
        ))}
      </ol>
      {filtered.length > 3 && (
        <button type="button" className="cs-link cq-all" onClick={() => setEverything((v) => !v)}>
          {everything ? 'Show fewer' : `Show all ${filtered.length}`}
        </button>
      )}
    </details>
  )
}

function LogCell({ log, active, onOpen }: { log: LogEntry[]; active: number | null; onOpen: (e: LogEntry) => void }) {
  if (!log.length) return null
  return (
    <section className="cg">
      <span className="cs-label">Register of questions</span>
      <table className="bd cg-table">
        <thead><tr><th scope="col">Ref.</th><th scope="col">Question</th><th scope="col" className="n">Answer</th><th scope="col">Status</th></tr></thead>
        <tbody>
          {log.map((e) => (
            <tr key={e.id} className={e.id === active ? 'is-on' : undefined} data-linked="" onClick={() => onOpen(e)}>
              <th scope="row">{ref(e.id)}</th>
              <td>
                <button type="button" onClick={(ev) => { ev.stopPropagation(); onOpen(e) }}>{e.answer.question}</button>
                <small>{drawingName(e.drawing.name)[0]}{e.region ? ' · cloud' : ''}</small>
              </td>
              <td className="n">{value(e.answer)}</td>
              <td className={`cg-st is-${e.answer.status}`}>{STATUS[e.answer.status][0]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function MicIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <rect x="5.5" y="1.5" width="5" height="8.5" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3 7.5a5 5 0 0 0 10 0M8 12.5V15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}
