import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import type { Answer, Drawing, Engine, Health } from './types'
import { TopBar } from './components/TopBar'
import { DrawingList } from './components/DrawingList'
import { SheetViewer } from './components/SheetViewer'
import { AskPanel } from './components/AskPanel'
import { AnswerCard } from './components/AnswerCard'

const RENDER_NOTE: Record<Drawing['render'], string | null> = {
  image: null,
  pdf: 'PDF page 1',
  dxf: 'Rendered from DXF twin',
}

export default function App() {
  const [drawings, setDrawings] = useState<Drawing[]>([])
  const [total, setTotal] = useState(0)
  const [listError, setListError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Drawing | null>(null)
  const [engine, setEngine] = useState<Engine>('auto')
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [askError, setAskError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [hovered, setHovered] = useState<number | null>(null)
  const inflight = useRef<AbortController | null>(null)

  // API health, re-checked every 15 s so the badge flips when the real router comes up.
  useEffect(() => {
    let alive = true
    const check = () =>
      api
        .health()
        .then((h) => alive && (setHealth(h), setHealthError(false)))
        .catch(() => alive && setHealthError(true))
    check()
    const t = setInterval(check, 15000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  useEffect(() => {
    api
      .drawings()
      .then((r) => {
        setDrawings(r.drawings)
        setTotal(r.total)
        const fromHash = decodeURIComponent(location.hash.slice(1))
        setSelected(r.drawings.find((d) => d.path === fromHash) ?? r.drawings[0] ?? null)
      })
      .catch((e: Error) => setListError(e.message))
  }, [])

  const select = useCallback((d: Drawing) => {
    inflight.current?.abort()
    setSelected(d)
    setAnswer(null)
    setAskError(null)
    setHovered(null)
    history.replaceState(null, '', `#${encodeURIComponent(d.path)}`)
  }, [])

  const ask = useCallback(
    async (question: string) => {
      if (!selected) return
      inflight.current?.abort()
      const ctrl = new AbortController()
      inflight.current = ctrl
      setBusy(true)
      setAskError(null)
      setHovered(null)
      try {
        const ref = selected.questions.find((q) => q.question === question)
        const a = await api.ask({ path: selected.path, question, type: ref?.type ?? null, engine }, ctrl.signal)
        setAnswer(a)
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setAnswer(null)
          setAskError((e as Error).message)
        }
      } finally {
        if (inflight.current === ctrl) setBusy(false)
      }
    },
    [selected, engine],
  )

  const reference = useMemo(
    () => (answer && selected ? selected.questions.find((q) => q.question === answer.question) ?? null : null),
    [answer, selected],
  )

  return (
    <div className="app">
      <TopBar engine={engine} onEngine={setEngine} health={health} healthError={healthError} />

      <div className="workspace">
        <DrawingList
          drawings={drawings}
          total={total}
          selected={selected?.path ?? null}
          error={listError}
          onSelect={select}
        />

        <main className="stage">
          <div className="stage-head">
            <div className="stage-title">
              <span className="mono muted">{selected?.collection ?? '—'}</span>
              <h1 className="mono">{selected?.name ?? 'No drawing selected'}</h1>
            </div>
            {selected && <span className="mono muted small path">{selected.path}</span>}
          </div>
          <SheetViewer
            src={selected ? api.drawingUrl(selected.path) : null}
            evidence={answer?.evidence ?? []}
            page={0}
            hovered={hovered}
            onHover={setHovered}
            renderNote={selected ? RENDER_NOTE[selected.render] : null}
          />
        </main>

        <aside className="inspector">
          <AskPanel key={selected?.path ?? 'none'} drawing={selected} busy={busy} onAsk={ask}>
          <div className="result">
            {answer && <p className="asked">“{answer.question}”</p>}
            {askError && (
              <div className="ask-error">
                <strong>Request failed.</strong> {askError}
              </div>
            )}
            {answer && (
              <AnswerCard answer={answer} reference={reference} hovered={hovered} onHover={setHovered} />
            )}
            {!answer && !askError && (
              <p className="result-empty muted">
                Ask a question about the sheet. The answer comes back with the items it counted or measured, marked on
                the drawing.
              </p>
            )}
          </div>
          </AskPanel>
        </aside>
      </div>
    </div>
  )
}
