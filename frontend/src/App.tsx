import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import type { Answer, Drawing, Engine, Health } from './types'
import { TopBar } from './components/TopBar'
import { DrawingList } from './components/DrawingList'
import { SheetViewer } from './components/SheetViewer'
import { AskPanel } from './components/AskPanel'
import { AnswerCard } from './components/AnswerCard'
import { speakableAnswer, useSpeaker, voiceApi } from './voice'

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
  const [voice, setVoice] = useState(false)
  const { speak, stop: stopSpeech, speaking, error: speechError } = useSpeaker()

  // Voice shows only when the backend has an ElevenLabs key.
  useEffect(() => {
    voiceApi
      .status()
      .then((s) => setVoice(s.enabled))
      .catch(() => setVoice(false))
  }, [])

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

  const interrupt = useCallback(() => {
    inflight.current?.abort()
    inflight.current = null
    stopSpeech()
    setBusy(false)
    setAskError(null)
  }, [stopSpeech])

  useEffect(() => () => { inflight.current?.abort() }, [])

  const select = useCallback((d: Drawing) => {
    interrupt()
    setSelected(d)
    setAnswer(null)
    setAskError(null)
    setHovered(null)
    history.replaceState(null, '', `#${encodeURIComponent(d.path)}`)
  }, [interrupt])

  const ask = useCallback(
    async (question: string, spoken = false) => {
      if (!selected) return
      inflight.current?.abort()
      stopSpeech()
      const ctrl = new AbortController()
      inflight.current = ctrl
      setBusy(true)
      setAskError(null)
      setHovered(null)
      try {
        const ref = selected.questions.find((q) => q.question === question)
        const a = await api.ask({ path: selected.path, question, type: ref?.type ?? null, engine }, ctrl.signal)
        if (ctrl.signal.aborted) return
        setAnswer(a)
        // Questions asked by voice get a spoken answer.
        if (spoken && !ctrl.signal.aborted) void speak(speakableAnswer(a))
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setAnswer(null)
          setAskError((e as Error).message)
        }
      } finally {
        if (inflight.current === ctrl) setBusy(false)
      }
    },
    [selected, engine, stopSpeech, speak],
  )

  const reference = useMemo(
    () => (answer && selected ? selected.questions.find((q) => q.question === answer.question) ?? null : null),
    [answer, selected],
  )

  return (
    <div className="app">
      <SheetViewer
        src={selected ? api.drawingUrl(selected.path) : null}
        evidence={answer?.evidence ?? []}
        page={0}
        hovered={hovered}
        onHover={setHovered}
        renderNote={selected ? RENDER_NOTE[selected.render] : null}
      />

      <TopBar
        engine={engine}
        onEngine={setEngine}
        health={health}
        healthError={healthError}
        title={selected?.name ?? null}
        subtitle={selected ? selected.collection.replace(/_/g, ' ') : null}
      />

      <DrawingList
        drawings={drawings}
        total={total}
        selected={selected?.path ?? null}
        error={listError}
        onSelect={select}
      />

      <aside className="inspector" aria-label="Ask about the drawing">
        <AskPanel key={selected?.path ?? 'none'} drawing={selected} busy={busy} onAsk={ask} voice={voice}
          speaking={speaking} voiceError={speechError ?? askError} onInterrupt={interrupt}>
          <div className="result" aria-busy={busy}>
            {askError && (
              <div className="ask-error">
                <strong>Request failed.</strong> {askError}
              </div>
            )}
            {answer && !busy && (
              <AnswerCard
                answer={answer}
                reference={reference}
                hovered={hovered}
                onHover={setHovered}
                speech={
                  voice
                    ? {
                        speaking: speaking,
                        error: speechError,
                        onToggle: () => (speaking ? stopSpeech() : void speak(speakableAnswer(answer))),
                      }
                    : undefined
                }
              />
            )}
            {busy && <p className="result-loading" role="status"><span className="loading-dot" /> Looking closely at the drawing…</p>}
            {!answer && !askError && !busy && (
              <p className="result-empty">
                Your answer will appear here, with the evidence marked on the drawing.
              </p>
            )}
          </div>
        </AskPanel>
      </aside>
    </div>
  )
}
