// The app's state and actions, with no markup. The Clár UI (ui/clar) renders from this hook; it
// behaves like the classic App.tsx and differs only in design.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { Answer, AreaMode, DatasetQuestion, Drawing, Engine, Health, Region } from '../types'
import { speakableAnswer, useSpeaker, voiceApi } from '../voice'

export interface LogEntry {
  id: number
  drawing: Drawing
  region: Region | null
  areaMode: AreaMode
  answer: Answer
  at: Date
}

export type ReadAloud = 'off' | 'spoken' | 'always'
export type GemmaState = 'available' | 'unavailable' | 'unconfigured' | 'checking' | 'disabled' | undefined

export function useSession() {
  const [drawings, setDrawings] = useState<Drawing[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [listLoading, setListLoading] = useState(true)
  const [selected, setSelected] = useState<Drawing | null>(null)
  const [engine, setEngine] = useState<Engine>('auto')
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [askError, setAskError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const [region, setRegion] = useState<Region | null>(null)
  const [selectingRegion, setSelectingRegion] = useState(false)
  const [areaMode, setAreaMode] = useState<AreaMode>('whole_rooms')
  const [log, setLog] = useState<LogEntry[]>([])
  const [activeEntry, setActiveEntry] = useState<number | null>(null)
  const [voice, setVoice] = useState(false)
  // When answers are read aloud: never, only after a spoken question, or after every question.
  const [readAloud, setReadAloudState] = useState<ReadAloud>(() => {
    try {
      const v = localStorage.getItem('leargas.readAloud')
      return v === 'off' || v === 'always' ? v : 'spoken'
    } catch { return 'spoken' }
  })
  const setReadAloud = useCallback((v: ReadAloud) => {
    setReadAloudState(v)
    try { localStorage.setItem('leargas.readAloud', v) } catch { /* private window */ }
  }, [])
  const inflight = useRef<AbortController | null>(null)
  const nextId = useRef(1)
  const speaker = useSpeaker()
  const { speak, stop: stopSpeech } = speaker

  useEffect(() => {
    voiceApi.status().then((s) => setVoice(s.enabled)).catch(() => setVoice(false))
  }, [])

  useEffect(() => {
    let alive = true
    const check = () =>
      api.health()
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
    api.drawings()
      .then((r) => {
        setDrawings((current) => [...r.drawings, ...current.filter((d) => !r.drawings.some((item) => item.path === d.path))])
        const fromHash = decodeURIComponent(location.hash.slice(1))
        setSelected((current) => current ?? r.drawings.find((d) => d.path === fromHash) ?? r.drawings[0] ?? null)
      })
      .catch((e: Error) => setListError(e.message))
      .finally(() => setListLoading(false))
  }, [])

  const cancel = useCallback(() => {
    inflight.current?.abort()
    inflight.current = null
    stopSpeech()
    setBusy(false)
    setPending(null)
  }, [stopSpeech])

  const resetAnswer = useCallback(() => {
    setAnswer(null)
    setAskError(null)
    setHovered(null)
    setActiveEntry(null)
  }, [])

  const select = useCallback((d: Drawing) => {
    cancel()
    resetAnswer()
    setSelected(d)
    setRegion(null)
    setAreaMode('whole_rooms')
    setSelectingRegion(false)
    history.replaceState(null, '', `${location.search}#${encodeURIComponent(d.path)}`)
  }, [cancel, resetAnswer])

  const uploaded = useCallback((added: Drawing[]) => {
    const prefixes = new Set(added.map((d) => d.path.replace(/\.[^.]+$/, '')))
    setDrawings((current) => [...added, ...current.filter((d) => !prefixes.has(d.path.replace(/\.[^.]+$/, '')))])
    if (added[0]) select(added[0])
  }, [select])

  const changeRegion = useCallback((next: Region | null) => {
    cancel()
    resetAnswer()
    setRegion(next)
    setSelectingRegion(false)
  }, [cancel, resetAnswer])

  const changeAreaMode = useCallback((next: AreaMode) => {
    cancel()
    resetAnswer()
    setAreaMode(next)
  }, [cancel, resetAnswer])

  const ask = useCallback(
    async (question: string, opts: { spoken?: boolean; floorAreas?: boolean } = {}) => {
      if (!selected) return
      const { spoken = false, floorAreas = false } = opts
      inflight.current?.abort()
      stopSpeech()
      const ctrl = new AbortController()
      inflight.current = ctrl
      setBusy(true)
      setPending(question)
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
        const id = nextId.current++
        setAnswer(a)
        setActiveEntry(id)
        setLog((l) => [{ id, drawing: selected, region, areaMode, answer: a, at: new Date() }, ...l].slice(0, 60))
        if (voice && (readAloud === 'always' || (spoken && readAloud === 'spoken'))) void speak(speakableAnswer(a))
      } catch (e) {
        if (!ctrl.signal.aborted && (e as Error).name !== 'AbortError') {
          setAnswer(null)
          setActiveEntry(null)
          setAskError((e as Error).message)
        }
      } finally {
        if (inflight.current === ctrl) {
          setBusy(false)
          setPending(null)
        }
      }
    },
    [selected, engine, region, areaMode, stopSpeech, speak, voice, readAloud],
  )

  /** Bring back an earlier answer, with its drawing and region. */
  const reopen = useCallback((entry: LogEntry) => {
    cancel()
    if (entry.drawing.path !== selected?.path) {
      setSelected(entry.drawing)
      history.replaceState(null, '', `${location.search}#${encodeURIComponent(entry.drawing.path)}`)
    }
    setRegion(entry.region)
    setAreaMode(entry.areaMode)
    setSelectingRegion(false)
    setAskError(null)
    setHovered(null)
    setAnswer(entry.answer)
    setActiveEntry(entry.id)
  }, [cancel, selected])

  const reference: DatasetQuestion | null = useMemo(
    () => (answer && selected && !answer.region && answer.area_mode !== 'intersection'
      ? selected.questions.find((q) => q.question === answer.question) ?? null : null),
    [answer, selected],
  )

  const gemmaModel = engine === 'gemma_base' ? 'gemma-base' : 'gemma-ft'
  const gemmaState = (health?.gemma_status?.models[gemmaModel] ?? health?.gemma_status?.status) as GemmaState
  const connection: 'offline' | 'connecting' | 'mock' | 'degraded' | 'live' = healthError ? 'offline'
    : !health ? 'connecting'
      : health.mode === 'mock' ? 'mock'
        : health.mode === 'live' && gemmaState && gemmaState !== 'available' ? 'degraded' : 'live'

  return {
    drawings, total: drawings.length, listError, listLoading,
    selected, select, uploaded,
    engine, setEngine, health, healthError, connection, gemmaState,
    answer, askError, busy, pending, ask, cancel, reference,
    hovered, setHovered,
    region, changeRegion, selectingRegion, setSelectingRegion,
    areaMode, changeAreaMode,
    log, activeEntry, reopen,
    voice, speaker, readAloud, setReadAloud,
  }
}

export type Session = ReturnType<typeof useSession>
