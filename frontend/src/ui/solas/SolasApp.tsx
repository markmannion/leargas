import { useEffect, useMemo, useRef, useState } from 'react'
import '@fontsource-variable/atkinson-hyperlegible-next/wght.css'
import '@fontsource-variable/atkinson-hyperlegible-mono/wght.css'
import './solas.css'
import { api } from '../../api'
import type { Answer, Drawing, Engine } from '../../types'
import { TYPE_LABEL } from '../../format'
import { useSession, type Session } from '../../core/session'
import { useViewport } from '../../core/viewport'
import { FORMAT_LABEL, collectionName, drawingName, suggestionsFor, vectorTwins } from '../../core/catalogue'
import { SOURCE_SHORT, explain, itemised, rejectedGuess, value, valueParts } from '../../core/explain'
import { shapeCentre } from '../../core/shapes'
import { OpeningTable, RoomTable, SlabTable, SourceTable } from '../../core/breakdowns'
import { UPLOAD_ACCEPT, useUpload } from '../../core/upload'
import { speakableAnswer, useVoiceInput } from '../../voice'
import { SolasSheet } from './SolasSheet'
import { SolasIndex } from './SolasIndex'

const ENGINES: { id: Engine; label: string }[] = [
  { id: 'auto', label: 'the best engine for the drawing' },
  { id: 'geometry', label: 'geometry only' },
  { id: 'sheet', label: 'the sheet reader only' },
  { id: 'gemma_ft', label: 'fine-tuned Gemma only' },
  { id: 'gemma_base', label: 'base Gemma only' },
]

const STATUS: Record<Answer['status'], string> = {
  verified: 'Verified',
  partial: 'Partly supported',
  disagreement: 'Engines disagree',
  cannot_verify: 'Held back',
}

const RENDER_NOTE: Record<Drawing['render'], string | null> = {
  image: null,
  pdf: 'PDF, page 1',
  dxf: 'Drawn from the DXF',
  none: 'IFC model: there is no sheet to show, but questions still work.',
}

export default function SolasApp() {
  const s = useSession()
  const [indexOpen, setIndexOpen] = useState(false)
  const [lit, setLit] = useState(true)
  const [draft, setDraft] = useState<{ path: string | undefined; text: string }>({ path: undefined, text: '' })
  const text = draft.path === s.selected?.path ? draft.text : ''
  const setText = (t: string) => setDraft({ path: s.selected?.path, text: t })
  const input = useRef<HTMLInputElement>(null)
  const file = useRef<HTMLInputElement>(null)
  const notes = useRef<HTMLDivElement>(null)
  const [dropping, setDropping] = useState(0)
  const up = useUpload((d) => { s.uploaded(d); setIndexOpen(false) })

  const src = s.selected && s.selected.render !== 'none' ? api.drawingUrl(s.selected.path) : null
  const vp = useViewport({ src, pad: 40, selectingRegion: s.selectingRegion, onRegion: s.changeRegion, onSelectingChange: s.setSelectingRegion })
  const evidence = s.answer?.evidence ?? []
  const highlighted = s.answer?.room_areas?.find((r) => s.hovered !== null && r.evidence_indices.includes(s.hovered))?.evidence_indices
  const pick = (i: number) => {
    const e = evidence[i]
    if (!e) return
    s.setHovered(i)
    vp.centreOn(shapeCentre(e.shape))
  }

  const blocked = !s.selected || s.busy || s.selectingRegion
  const ask = (q: string, opts: { spoken?: boolean; floorAreas?: boolean } = {}) => {
    const t = q.trim()
    if (!t || blocked) return
    setText(t)
    void s.ask(t, opts)
  }
  const mic = useVoiceInput((t) => ask(t, { spoken: true }))

  useEffect(() => { notes.current?.scrollTo({ top: 0 }) }, [s.activeEntry, s.busy])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === '/' && !(e.target as Element).closest('input, textarea, select')) { e.preventDefault(); input.current?.focus() }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])

  const [main, sub] = s.selected ? drawingName(s.selected.name) : ['No drawing', '']
  const a = s.answer

  return (
    <div className="solas"
      onDragEnter={(e) => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); setDropping((n) => n + 1) } }}
      onDragOver={(e) => { if (dropping) e.preventDefault() }}
      onDragLeave={() => setDropping((n) => Math.max(0, n - 1))}
      onDrop={(e) => { if (!dropping) return; e.preventDefault(); setDropping(0); void up.upload(e.dataTransfer.files) }}>

      <header className="so-band">
        <div className="so-row1">
          <span className="so-word">Léargas</span>
          <button type="button" className="so-drawing" onClick={() => setIndexOpen((o) => !o)} aria-expanded={indexOpen}
            title={s.selected?.path}>
            <strong>{s.listLoading && !s.selected ? 'Loading drawings' : main}</strong>
            {s.selected && <span>{[sub, collectionName(s.selected.collection), FORMAT_LABEL[s.selected.render]].filter(Boolean).join(' · ')}</span>}
            <i aria-hidden="true">{indexOpen ? 'close' : 'change'}</i>
          </button>
          <span className="so-gap" />
          <label className="so-engine">
            <span>Answer with</span>
            <select value={s.engine} onChange={(e) => s.setEngine(e.target.value as Engine)}>
              {ENGINES.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
            </select>
          </label>
          <Connection s={s} />
        </div>

        <form className="so-ask" onSubmit={(e) => { e.preventDefault(); ask(text) }}>
          <input ref={input} className="so-q" value={text} disabled={!s.selected} autoComplete="off" spellCheck={false}
            aria-label="Question about the drawing"
            placeholder={!s.selected ? 'Choose a drawing first' : s.region ? 'How many doors are in the box?' : 'How many bedrooms are on this floor?'}
            onChange={(e) => setText(e.target.value)} />
          {s.voice && (
            <button type="button" className={`so-mic is-${mic.state}`} onClick={mic.toggle} disabled={blocked || mic.state === 'transcribing'}
              aria-pressed={mic.state === 'recording'} title={mic.error ?? undefined}>
              {mic.state === 'recording' ? 'Stop' : mic.state === 'transcribing' ? 'Listening' : 'Speak'}
            </button>
          )}
          <button type="submit" className="so-go" disabled={blocked || !text.trim()}>Ask</button>
        </form>

        <Result s={s} />
      </header>

      <main className="so-main">
        <section className="so-stage" aria-label="Sheet">
          <SolasSheet vp={vp} evidence={evidence} lit={lit} hovered={s.hovered} highlighted={highlighted} onHover={s.setHovered}
            region={s.region} selecting={s.selectingRegion} dark={Boolean(a && a.status !== 'cannot_verify') || s.selectingRegion || Boolean(s.region)} />
          <div className="so-tools" data-no-pan role="toolbar" aria-label="Sheet tools">
            <button type="button" onClick={() => vp.zoomBy(1 / 1.25)} aria-label="Zoom out">−</button>
            <span className="so-zoom">{Math.round(vp.view.k * 100)}%</span>
            <button type="button" onClick={() => vp.zoomBy(1.25)} aria-label="Zoom in">+</button>
            <button type="button" onClick={vp.fit}>Fit</button>
            <span className="so-tsep" />
            <button type="button" aria-pressed={s.selectingRegion} disabled={vp.state !== 'ready'}
              onClick={() => s.setSelectingRegion(!s.selectingRegion)}>
              {s.selectingRegion ? 'Cancel' : s.region ? 'Redraw box' : 'Box a region'}
            </button>
            {s.region && <button type="button" onClick={() => s.changeRegion(null)}>Whole sheet</button>}
            {evidence.length > 0 && (
              <>
                <span className="so-tsep" />
                <button type="button" aria-pressed={lit} onClick={() => setLit(!lit)}>{lit ? 'Lights on' : 'Lights off'}</button>
              </>
            )}
          </div>
          {(s.selectingRegion || (s.selected && RENDER_NOTE[s.selected.render])) && (
            <p className="so-note" data-no-pan>
              {s.selectingRegion ? vp.hint ?? 'Drag a box over the part of the sheet you mean. Esc cancels.' : RENDER_NOTE[s.selected!.render]}
            </p>
          )}
          {indexOpen && (
            <SolasIndex drawings={s.drawings} selected={s.selected?.path ?? null} loading={s.listLoading} error={s.listError}
              onSelect={(d) => { s.select(d); setIndexOpen(false) }} onAdd={() => file.current?.click()} onClose={() => setIndexOpen(false)} />
          )}
        </section>

        <aside className="so-notes" ref={notes} aria-label="Notes">
          <input ref={file} type="file" hidden multiple accept={UPLOAD_ACCEPT}
            onChange={(e) => { void up.upload(e.currentTarget.files); e.currentTarget.value = '' }} />
          {(up.busy || up.error || up.message) && (
            <p className={`sn-line${up.error ? ' is-bad' : ''}`} role="status">
              {up.busy ? (up.progress === 100 ? 'Preparing the drawing…' : `Uploading, ${up.progress}%`) : up.error ?? up.message}
            </p>
          )}
          {s.askError && <p className="sn-line is-bad">The request failed. {s.askError}</p>}
          {s.connection === 'degraded' && (
            <p className="sn-line">
              {s.gemmaState === 'checking' ? 'Checking whether Gemma is up.' : s.gemmaState === 'unconfigured' ? 'Gemma is not connected.' : 'Gemma is offline for now.'}
              {' '}Geometry and the sheet reader still answer.
            </p>
          )}

          {a && !s.busy && <Why s={s} a={a} lit={lit} onPick={pick} />}

          <Tools s={s} ask={ask} />
          <Suggestions s={s} text={text} ask={ask} />
          <Earlier s={s} onOpen={(e) => { s.reopen(e); setDraft({ path: e.drawing.path, text: e.answer.question }) }} />
        </aside>
      </main>

      {dropping > 0 && (
        <div className="so-drop" aria-hidden="true">
          <p>Drop to add the drawing</p>
          <span>PDF, PNG, JPEG, DXF or IFC, up to 25 MB each. Files with the same name are paired, so plan.pdf and plan.dxf become one drawing checked against its geometry.</span>
        </div>
      )}
    </div>
  )
}

function Connection({ s }: { s: Session }) {
  const text = {
    offline: 'Backend offline',
    connecting: 'Connecting',
    mock: 'Mock API',
    live: 'Connected',
    degraded: s.gemmaState === 'checking' ? 'Checking Gemma' : s.gemmaState === 'unconfigured' ? 'Geometry only' : 'Gemma offline',
  }[s.connection]
  return <span className={`so-conn is-${s.connection}`} role="status"
    title={s.health ? `${s.health.gold_questions_loaded.toLocaleString()} reference questions loaded` : undefined}>{text}</span>
}

function Result({ s }: { s: Session }) {
  const a = s.answer
  if (s.busy) return <div className="so-result is-busy" role="status"><p className="so-wait">Reading the drawing</p></div>
  if (!a) return <div className="so-result is-idle"><p>The answer appears here. What it is based on lights up on the sheet.</p></div>
  const [num, unit] = valueParts(a)
  const cv = a.status === 'cannot_verify'
  const long = typeof a.answer === 'string' && a.answer.length > 14
  return (
    <div className={`so-result is-${a.status}`} aria-live="polite">
      <p className={`so-value${long ? ' is-text' : ''}`}>
        {cv ? <span className="so-num">—</span> : <><span className="so-num">{num}</span>{unit && <span className="so-unit">{unit}</span>}</>}
      </p>
      <p className="so-status">
        <span className="so-st">{STATUS[a.status]}</span>
        {!cv && <> · {SOURCE_SHORT[a.source]}</>}
        {a.latency_ms != null && <span className="so-ms"> · {a.latency_ms < 1000 ? `${Math.max(1, Math.round(a.latency_ms))} ms` : `${(a.latency_ms / 1000).toFixed(1)} s`}</span>}
      </p>
    </div>
  )
}

function Why({ s, a, lit, onPick }: { s: Session; a: Answer; lit: boolean; onPick: (i: number) => void }) {
  const lines = explain(a, s.reference)
  const linked = { answer: a, hovered: s.hovered, onHover: s.setHovered, onPick }
  const guess = rejectedGuess(a)
  const sources = new Set(a.evidence.map((e) => e.source === 'gemma_ft' || e.source === 'gemma_base' ? 'soft' : e.source === 'sheet_reader' ? 'read' : 'sharp'))
  const sp = s.speaker
  return (
    <section className={`sn-why is-${a.status}`}>
      <div className="sn-head">
        <h2>{TYPE_LABEL[a.type]}{a.region ? ', inside the box' : ''}</h2>
        {s.voice && (
          <button type="button" className="sn-link" onClick={() => (sp.speaking ? sp.stop() : void sp.speak(speakableAnswer(a)))} title={sp.error ?? undefined}>
            {sp.speaking ? 'Stop reading' : 'Read it aloud'}
          </button>
        )}
      </div>
      {lines.map((l, i) => <p key={i} className={i === 0 ? 'sn-lead' : undefined}>{l}</p>)}
      {a.explanation && <blockquote className="sn-quote">{a.explanation}</blockquote>}
      {guess && <p className="sn-dim">Nothing is lit on the sheet, because nothing was accepted.</p>}

      <SourceTable answer={a} />
      <RoomTable {...linked} />
      <SlabTable {...linked} />
      <OpeningTable {...linked} />

      {a.evidence.length > 0 && !itemised(a) && (
        <div className="sn-block">
          <h3>On the sheet</h3>
          <ol className="sn-ev">
            {a.evidence.map((e, i) => (
              <li key={i} className={s.hovered === i ? 'is-on' : undefined}>
                <button type="button" onPointerEnter={() => s.setHovered(i)} onPointerLeave={() => s.setHovered(null)}
                  onFocus={() => s.setHovered(i)} onBlur={() => s.setHovered(null)} onClick={() => onPick(i)}>
                  <span className="sn-n">{i + 1}</span>
                  <span>{e.label ?? (e.shape.kind === 'point' ? 'Point' : e.shape.kind === 'bbox' ? 'Area' : 'Outline')}</span>
                  {e.value != null && <span className="sn-v">{value({ ...a, answer: e.value })}</span>}
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {a.evidence.length > 0 && lit && (
        <p className="sn-legend">
          {sources.has('sharp') && <span><i className="l-sharp" />Sharp light: measured from geometry.</span>}
          {sources.has('read') && <span><i className="l-read" />Softer light: read from the sheet’s text.</span>}
          {sources.has('soft') && <span><i className="l-soft" />Soft light: the model’s estimate.</span>}
        </p>
      )}
    </section>
  )
}

function Tools({ s, ask }: { s: Session; ask: (q: string, o?: { floorAreas?: boolean }) => void }) {
  const blocked = !s.selected || s.busy || s.selectingRegion
  const twins = s.selected ? vectorTwins(s.selected) : []
  return (
    <section className="sn-block sn-tools">
      <h3>Measure</h3>
      <div className="sn-row">
        <button type="button" className="sn-link" disabled={blocked} onClick={() => ask('Show floor areas by room', { floorAreas: true })}>
          {s.region && s.areaMode === 'intersection' ? 'Floor area inside the box' : 'Floor area by room'}
        </button>
        <button type="button" className="sn-link" disabled={blocked || Boolean(s.region)} title={s.region ? 'Slab areas use the whole sheet' : undefined}
          onClick={() => ask('Slab area by type (thickness and bars)')}>Slab area by type</button>
      </div>
      {s.region && (
        <fieldset className="sn-mode">
          <legend>Rooms the box cuts through</legend>
          <label><input type="radio" name="so-mode" checked={s.areaMode === 'whole_rooms'} onChange={() => s.changeAreaMode('whole_rooms')} /> count whole</label>
          <label><input type="radio" name="so-mode" checked={s.areaMode === 'intersection'} onChange={() => s.changeAreaMode('intersection')} /> count only the part inside</label>
        </fieldset>
      )}
      {twins.length > 0 && s.selected?.render !== 'dxf' && s.selected?.render !== 'none' && (
        <p className="sn-dim">This upload has a {twins.join(' and ')} file, so geometry can check the answers.</p>
      )}
    </section>
  )
}

function Suggestions({ s, text, ask }: { s: Session; text: string; ask: (q: string) => void }) {
  const all = useMemo(() => suggestionsFor(s.selected), [s.selected])
  const asked = s.answer?.question
  const terms = text.trim().toLowerCase()
  // While typing, the list narrows to questions containing what has been typed.
  const shown = all.filter((q) => q.question !== asked && (!terms || terms === asked?.toLowerCase() || q.question.toLowerCase().includes(terms)))
  if (!all.length) return null
  return (
    <section className="sn-block sn-qs">
      <h3>{all[0].fromDataset ? 'Questions from the dataset' : 'Questions to try'} <span>{shown.length}</span></h3>
      {shown.length === 0 && <p className="sn-dim">None of them contain “{text.trim()}”. Press Enter to ask it anyway.</p>}
      <ul>
        {shown.map((q, i) => (
          <li key={i}>
            <button type="button" disabled={s.busy || s.selectingRegion || !s.selected} onClick={() => ask(q.question)}
              title={q.weak ? 'The model rarely counts doors and windows right from the image alone, so it will usually hold the answer back.' : undefined}>
              {q.question}
              <span>{q.lang}{q.weak ? ' · the model is unreliable here' : ''}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Earlier({ s, onOpen }: { s: Session; onOpen: (e: Session['log'][number]) => void }) {
  const items = s.log.filter((e) => e.id !== s.activeEntry)
  if (!items.length) return null
  return (
    <section className="sn-block sn-earlier">
      <h3>Asked earlier</h3>
      <ul>
        {items.map((e) => (
          <li key={e.id}>
            <button type="button" onClick={() => onOpen(e)}>
              <span className="sn-eq">{e.answer.question}</span>
              <span className={`sn-ea is-${e.answer.status}`}>{e.answer.status === 'cannot_verify' ? 'held back' : value(e.answer)}</span>
              <span className="sn-ed">{drawingName(e.drawing.name)[0]}{e.region ? ', in a box' : ''} · {e.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
