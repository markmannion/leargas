import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import type { Answer, AreaMode, Drawing, Engine, Health, Region } from './types'
import { TopBar } from './components/TopBar'
import { DrawingList } from './components/DrawingList'
import { SheetViewer } from './components/SheetViewer'
import { AskPanel } from './components/AskPanel'
import { AnswerCard } from './components/AnswerCard'
import { speakableAnswer, useSpeaker, voiceApi } from './voice'
import './region.css'

const RENDER_NOTE: Record<Drawing['render'], string | null> = {
  image: null,
  pdf: 'PDF page 1',
  dxf: 'Rendered from DXF twin',
  none: 'No sheet to show for an IFC model',
}

export default function App() {
  const [drawings, setDrawings] = useState<Drawing[]>([])
  const total = drawings.length
  const [listError, setListError] = useState<string | null>(null)
  const [listLoading, setListLoading] = useState(true)
  const [selected, setSelected] = useState<Drawing | null>(null)
  const [engine, setEngine] = useState<Engine>('auto')
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [askError, setAskError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [hovered, setHovered] = useState<number | null>(null)
  const [region, setRegion] = useState<Region | null>(null)
  const [selectingRegion, setSelectingRegion] = useState(false)
  const [areaMode, setAreaMode] = useState<AreaMode>('whole_rooms')
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
        setDrawings((current) => [...r.drawings, ...current.filter((d) => !r.drawings.some((item) => item.path === d.path))])
        const fromHash = decodeURIComponent(location.hash.slice(1))
        setSelected((current) => current ?? r.drawings.find((d) => d.path === fromHash) ?? r.drawings[0] ?? null)
      })
      .catch((e: Error) => setListError(e.message))
      .finally(() => setListLoading(false))
  }, [])

  const select = useCallback((d: Drawing) => {
    inflight.current?.abort()
    inflight.current = null
    stopSpeech()
    setBusy(false)
    setSelected(d)
    setRegion(null)
    setAreaMode('whole_rooms')
    setSelectingRegion(false)
    setAnswer(null)
    setAskError(null)
    setHovered(null)
    history.replaceState(null, '', `#${encodeURIComponent(d.path)}`)
  }, [stopSpeech])

  const uploaded = useCallback((added: Drawing[]) => {
    const prefixes = new Set(added.map((d) => d.path.replace(/\.[^.]+$/, '')))
    setDrawings((current) => [...added, ...current.filter((d) => !prefixes.has(d.path.replace(/\.[^.]+$/, '')))])
    if (added[0]) select(added[0])
  }, [select])

  const changeRegion = useCallback((next: Region | null) => {
    inflight.current?.abort()
    inflight.current = null
    stopSpeech()
    setBusy(false)
    setRegion(next)
    setSelectingRegion(false)
    setAnswer(null)
    setAskError(null)
    setHovered(null)
  }, [stopSpeech])

  const changeAreaMode = useCallback((next: AreaMode) => {
    inflight.current?.abort()
    inflight.current = null
    stopSpeech()
    setBusy(false)
    setAreaMode(next)
    setAnswer(null)
    setAskError(null)
    setHovered(null)
  }, [stopSpeech])

  const ask = useCallback(
    async (question: string, spoken = false, floorAreas = false) => {
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
        const isArea = floorAreas || (ref ? ref.type === 'area'
          : !/\b(how many|count|number of)\b/i.test(question) && /\b(area|areas|fläche|surface|pinta-ala)\b|m²|m2/i.test(question))
        const a = await api.ask({
          path: selected.path, question, type: floorAreas ? 'area' : ref?.type ?? null, engine, region,
          area_mode: region && isArea ? areaMode : 'whole_rooms',
          room_breakdown: floorAreas,
        }, ctrl.signal)
        if (ctrl.signal.aborted) return
        setAnswer(a)
        // Questions asked by voice get a spoken answer.
        if (spoken && !ctrl.signal.aborted) void speak(speakableAnswer(a))
      } catch (e) {
        if (!ctrl.signal.aborted && (e as Error).name !== 'AbortError') {
          setAnswer(null)
          setAskError((e as Error).message)
        }
      } finally {
        if (inflight.current === ctrl) setBusy(false)
      }
    },
    [selected, engine, region, areaMode, stopSpeech, speak],
  )

  const reference = useMemo(
    () => (answer && selected && !answer.region && answer.area_mode !== 'intersection' ? selected.questions.find((q) => q.question === answer.question) ?? null : null),
    [answer, selected],
  )

  const gemmaModel = engine === 'gemma_base' ? 'gemma-base' : 'gemma-ft'
  const gemmaLabel = engine === 'gemma_base' ? 'Gemma Base' : 'Fine-tuned Gemma'
  const gemmaState = health?.gemma_status?.models[gemmaModel] ?? health?.gemma_status?.status

  return (
    <div className="app">
      <SheetViewer
        key={selected?.path ?? 'none'}
        src={selected && selected.render !== 'none' ? api.drawingUrl(selected.path) : null}
        evidence={answer?.evidence ?? []}
        highlighted={answer?.room_areas?.find((room) => hovered !== null && room.evidence_indices.includes(hovered))?.evidence_indices}
        page={0}
        hovered={hovered}
        onHover={setHovered}
        renderNote={selected ? RENDER_NOTE[selected.render] : null}
        region={region}
        selectingRegion={selectingRegion}
        onRegionChange={changeRegion}
        onSelectionModeChange={setSelectingRegion}
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
        loading={listLoading}
        onSelect={select}
        onUploaded={uploaded}
      />

      <aside className="inspector glass">
        <AskPanel
          key={selected?.path ?? 'none'} drawing={selected} busy={busy} onAsk={ask} voice={voice}
          region={region} selectingRegion={selectingRegion}
          onSelectRegion={() => setSelectingRegion((active) => !active)}
          onClearRegion={() => changeRegion(null)}
          areaMode={areaMode} onAreaMode={changeAreaMode}
          onMeasureAreas={() => void ask('Show floor areas by room', false, true)}
        >
          <div className="result">
            {!healthError && health?.mode === 'live' && gemmaState && gemmaState !== 'available' && (
              <p className="model-notice" role="status">
                {gemmaState === 'checking'
                  ? 'Checking Gemma availability.'
                  : gemmaState === 'unconfigured'
                    ? 'Gemma is not connected.'
                    : `${gemmaLabel} is temporarily offline.`}{' '}
                Geometry and cached answers remain available.
                {gemmaState !== 'unconfigured' && ' Reconnecting automatically.'}
              </p>
            )}
            {askError && (
              <div className="ask-error">
                <strong>Request failed.</strong> {askError}
              </div>
            )}
            {answer && (
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
            {!answer && !askError && (
              <p className="result-empty">
                Ask about anything on the drawing. Answers come back with the items counted or measured, marked on
                the plan.
              </p>
            )}
          </div>
        </AskPanel>
      </aside>
    </div>
  )
}
