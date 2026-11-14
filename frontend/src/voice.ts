import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE } from './api'
import type { Answer, Unit } from './types'

async function check(res: Response): Promise<Response> {
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    let detail = body
    try { detail = (JSON.parse(body) as { detail?: string }).detail ?? body } catch { /* plain text */ }
    throw new Error(detail || `${res.status} ${res.statusText}`)
  }
  return res
}

export const voiceApi = {
  status: () => fetch(`${API_BASE}/voice/status`).then(check)
    .then((r) => r.json() as Promise<{ enabled: boolean }>),
  transcribe: (audio: Blob, signal?: AbortSignal) => fetch(`${API_BASE}/voice/transcribe`, {
    method: 'POST', headers: { 'Content-Type': audio.type || 'audio/webm' }, body: audio, signal,
  }).then(check).then((r) => r.json() as Promise<{ text: string; language_code: string | null }>),
  speak: (text: string, signal?: AbortSignal) => fetch(`${API_BASE}/voice/speak`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }), signal,
  }).then(check).then((r) => r.blob()),
}

const UNIT_WORDS: Record<Unit, string> = {
  count: '', m: 'metres', m2: 'square metres', m3: 'cubic metres',
  ft: 'feet', ft2: 'square feet', ft3: 'cubic feet',
}

export function speakableAnswer(a: Answer): string {
  if (a.status === 'cannot_verify' || a.answer == null) return "I can't verify that from this drawing. Try asking about a specific room or feature."
  const value = typeof a.answer === 'string' ? a.answer.slice(0, 600)
    : `${Number.isInteger(a.answer) ? a.answer : Number(a.answer.toFixed(2))}${a.unit && UNIT_WORDS[a.unit] ? ` ${UNIT_WORDS[a.unit]}` : ''}`
  if (a.status === 'partial') return `It looks like ${value}, though I can only partly verify that from the drawing.`
  if (a.status === 'disagreement') return `The sources disagree on this one. The best estimate is ${value}.`
  const sentence = typeof a.answer === 'number' ? (a.type === 'count' ? `I count ${value}.` : `That comes to ${value}.`) : `${value.replace(/[.!?]+$/, '')}.`
  return `${sentence}${a.evidence.length ? " You can see the evidence marked on the drawing." : ''}`
}

export type RecState = 'idle' | 'requesting' | 'recording' | 'transcribing'

/** One utterance, ended by a natural pause. All async work belongs to a cancellable turn. */
export function useVoiceInput(onText: (text: string) => void) {
  const [state, setState] = useState<RecState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [level, setLevel] = useState(0)
  const cb = useRef(onText)
  cb.current = onText
  const turn = useRef(0)
  const active = useRef(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const context = useRef<AudioContext | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const inflight = useRef<AbortController | null>(null)

  const release = useCallback(() => {
    if (timer.current) clearInterval(timer.current)
    timer.current = null
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (context.current) void context.current.close().catch(() => {})
    context.current = null
  }, [])

  const cancel = useCallback(() => {
    turn.current++
    active.current = false
    inflight.current?.abort()
    const r = recorder.current
    recorder.current = null
    if (r && r.state !== 'inactive') {
      r.onstop = null
      r.stop()
    }
    release()
    setState('idle')
    setLevel(0)
  }, [release])

  useEffect(() => () => {
    turn.current++
    active.current = false
    inflight.current?.abort()
    const r = recorder.current
    if (r && r.state !== 'inactive') { r.onstop = null; r.stop() }
    release()
  }, [release])

  const start = useCallback(async () => {
    if (active.current) return
    setError(null)
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined' || typeof AudioContext === 'undefined') {
      setError('Voice needs a browser with microphone recording support on HTTPS or localhost.')
      return
    }
    active.current = true
    const id = ++turn.current
    setState('requesting')
    try {
      // Create/resume from the user gesture on the first turn (required by Safari).
      const ctx = new AudioContext()
      context.current = ctx
      await ctx.resume()
      if (turn.current !== id) return
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      if (turn.current !== id) { stream.getTracks().forEach((t) => t.stop()); return }
      streamRef.current = stream
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find((t) => MediaRecorder.isTypeSupported(t))
      const r = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorder.current = r
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 2048
      ctx.createMediaStreamSource(stream).connect(analyser)
      const samples = new Float32Array(analyser.fftSize)
      const chunks: Blob[] = []
      let speechMs = 0
      let lastSpeech = performance.now()
      const began = lastSpeech
      r.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
      r.onerror = () => {
        if (turn.current !== id) return
        cancel()
        setError('The microphone disconnected. Start voice again to reconnect.')
      }
      r.onstop = async () => {
        release()
        recorder.current = null
        if (turn.current !== id) return
        setLevel(0)
        const blob = new Blob(chunks, { type: r.mimeType || 'audio/webm' })
        if (!blob.size || speechMs < 200) {
          active.current = false
          setState('idle')
          setError("I didn't hear a question. Start voice when you're ready.")
          return
        }
        const ctrl = new AbortController()
        inflight.current = ctrl
        setState('transcribing')
        try {
          const { text } = await voiceApi.transcribe(blob, ctrl.signal)
          if (turn.current !== id) return
          if (text.trim()) cb.current(text.trim())
          else setError("I didn't catch that. Please try again.")
        } catch (e) {
          if (turn.current === id && (e as Error).name !== 'AbortError') setError((e as Error).message)
        } finally {
          if (turn.current === id) { active.current = false; setState('idle') }
        }
      }
      r.start()
      setState('recording')
      timer.current = setInterval(() => {
        analyser.getFloatTimeDomainData(samples)
        const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length)
        setLevel(Math.min(1, rms * 12))
        const now = performance.now()
        if (rms > 0.018) { speechMs += 80; lastSpeech = now }
        // Allow a thoughtful pause mid-question; never send an empty or endless recording.
        if ((speechMs >= 200 && now - lastSpeech > 1500) || (speechMs < 200 && now - began > 12000) || now - began > 60000) {
          if (r.state === 'recording') r.stop()
          if (timer.current) clearInterval(timer.current)
          timer.current = null
        }
      }, 80)
    } catch (e) {
      if (turn.current !== id) return
      release()
      active.current = false
      setState('idle')
      const name = (e as Error).name
      setError(name === 'NotAllowedError' ? 'Allow microphone access in your browser, then try again.'
        : name === 'NotFoundError' ? 'No microphone found. Connect one and try again.' : 'Could not start the microphone. Please try again.')
    }
  }, [cancel, release])

  const finish = useCallback(() => {
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }, [])

  return { state, error, level, start, finish, cancel }
}

/** Cancellation also guards playback after a response has already finished downloading. */
export function useSpeaker() {
  const [speaking, setSpeaking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  const inflight = useRef<AbortController | null>(null)

  const stop = useCallback(() => {
    inflight.current?.abort()
    inflight.current = null
    setError(null)
    if (audio.current) {
      audio.current.pause()
      audio.current.onended = null
      audio.current.onerror = null
      URL.revokeObjectURL(audio.current.src)
      audio.current = null
    }
    setSpeaking(false)
  }, [])

  const speak = useCallback(async (text: string) => {
    stop()
    setError(null)
    const ctrl = new AbortController()
    inflight.current = ctrl
    setSpeaking(true)
    try {
      const blob = await voiceApi.speak(text, ctrl.signal)
      if (ctrl.signal.aborted) return
      const el = new Audio(URL.createObjectURL(blob))
      audio.current = el
      el.onended = () => { if (audio.current === el) stop() }
      el.onerror = () => {
        if (audio.current === el) { stop(); setError('Audio could not play. You can read the answer below.') }
      }
      await el.play()
    } catch (e) {
      if (!ctrl.signal.aborted) { stop(); setError((e as Error).message) }
    }
  }, [stop])

  useEffect(() => stop, [stop])
  return { speak, stop, speaking, error }
}
