import { useCallback, useEffect, useRef, useState } from 'react'
import { API_BASE } from './api'
import type { Answer, Unit } from './types'

async function check(res: Response): Promise<Response> {
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    let detail = body
    try {
      detail = (JSON.parse(body) as { detail?: string }).detail ?? body
    } catch {
      /* plain text */
    }
    throw new Error(detail || `${res.status} ${res.statusText}`)
  }
  return res
}

export const voiceApi = {
  status: () =>
    fetch(`${API_BASE}/voice/status`)
      .then(check)
      .then((r) => r.json() as Promise<{ enabled: boolean }>),

  transcribe: (audio: Blob) =>
    fetch(`${API_BASE}/voice/transcribe`, {
      method: 'POST',
      headers: { 'Content-Type': audio.type || 'audio/webm' },
      body: audio,
    })
      .then(check)
      .then((r) => r.json() as Promise<{ text: string; language_code: string | null }>),

  speak: (text: string, signal?: AbortSignal) =>
    fetch(`${API_BASE}/voice/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal,
    })
      .then(check)
      .then((r) => r.blob()),
}

const UNIT_WORDS: Record<Unit, string> = {
  count: '',
  m: 'metres',
  m2: 'square metres',
  m3: 'cubic metres',
  ft: 'feet',
  ft2: 'square feet',
  ft3: 'cubic feet',
}

function spokenValue(a: Answer): string {
  const v = a.answer
  if (v === null || v === undefined) return 'no answer'
  if (typeof v === 'string') return v.slice(0, 600)
  const n = Number.isInteger(v) ? v.toString() : v.toFixed(v >= 100 ? 0 : 1)
  const u = a.unit ? UNIT_WORDS[a.unit] : ''
  return u ? `${n} ${u}` : n
}

/** One short sentence the TTS reads back. */
export function speakableAnswer(a: Answer): string {
  const v = spokenValue(a)
  switch (a.status) {
    case 'verified':
      return `${v}.`
    case 'partial':
      return `Probably ${v}, but the evidence only partly supports it.`
    case 'disagreement':
      return `The sources disagree. My best answer is ${v}.`
    case 'cannot_verify':
      return "I can't verify that from this drawing."
  }
}

export type RecState = 'idle' | 'recording' | 'transcribing'

/** Click-to-start, click-to-stop recorder that hands the transcript to `onText`. */
export function useVoiceInput(onText: (text: string) => void) {
  const [state, setState] = useState<RecState>('idle')
  const [error, setError] = useState<string | null>(null)
  // Live input level while recording, 0-1 in steps of 0.1, so the UI can show it is being talked to.
  const [level, setLevel] = useState(0)
  const rec = useRef<MediaRecorder | null>(null)
  const meter = useRef<{ ctx: AudioContext; raf: number } | null>(null)
  const cb = useRef(onText)
  cb.current = onText

  const stopMeter = useCallback(() => {
    const m = meter.current
    if (!m) return
    cancelAnimationFrame(m.raf)
    void m.ctx.close()
    meter.current = null
    setLevel(0)
  }, [])

  const startMeter = useCallback((stream: MediaStream) => {
    try {
      const ctx = new AudioContext()
      void ctx.resume() // created after the permission prompt, so it can start suspended
      const an = ctx.createAnalyser()
      an.fftSize = 512
      ctx.createMediaStreamSource(stream).connect(an)
      const buf = new Uint8Array(an.fftSize)
      let last = -1
      const tick = () => {
        an.getByteTimeDomainData(buf)
        let sum = 0
        for (const b of buf) sum += ((b - 128) / 128) ** 2
        const v = Math.min(1, Math.round(Math.sqrt(sum / buf.length) * 60) / 10)
        if (v !== last) setLevel((last = v))
        if (meter.current) meter.current.raf = requestAnimationFrame(tick)
      }
      meter.current = { ctx, raf: requestAnimationFrame(tick) }
    } catch {
      // No Web Audio: recording still works, there is just no meter.
    }
  }, [])

  useEffect(
    () => () => {
      stopMeter()
      const r = rec.current
      if (r && r.state !== 'inactive') {
        r.onstop = null
        r.stop()
        r.stream.getTracks().forEach((t) => t.stop())
      }
    },
    [stopMeter],
  )

  const start = useCallback(async () => {
    setError(null)
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setError('Microphone access was blocked.')
      return
    }
    const r = new MediaRecorder(stream)
    const chunks: Blob[] = []
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data)
    r.onstop = async () => {
      stopMeter()
      stream.getTracks().forEach((t) => t.stop())
      rec.current = null
      const blob = new Blob(chunks, { type: r.mimeType || 'audio/webm' })
      if (!blob.size) return setState('idle')
      setState('transcribing')
      try {
        const { text } = await voiceApi.transcribe(blob)
        if (text) cb.current(text)
        else setError("Didn't catch that. Try again.")
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setState('idle')
      }
    }
    rec.current = r
    r.start()
    startMeter(stream)
    setState('recording')
  }, [startMeter, stopMeter])

  const stop = useCallback(() => rec.current?.stop(), [])

  const toggle = useCallback(() => {
    if (state === 'recording') stop()
    else if (state === 'idle') void start()
  }, [state, start, stop])

  return { state, error, toggle, level }
}

/** Plays answers through ElevenLabs TTS; a new call cuts off the previous one. */
export function useSpeaker() {
  const [speaking, setSpeaking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  const inflight = useRef<AbortController | null>(null)

  const stop = useCallback(() => {
    inflight.current?.abort()
    if (audio.current) {
      audio.current.pause()
      URL.revokeObjectURL(audio.current.src)
      audio.current = null
    }
    setSpeaking(false)
  }, [])

  const speak = useCallback(
    async (text: string) => {
      stop()
      setError(null)
      const ctrl = new AbortController()
      inflight.current = ctrl
      setSpeaking(true)
      try {
        const blob = await voiceApi.speak(text, ctrl.signal)
        const el = new Audio(URL.createObjectURL(blob))
        audio.current = el
        el.onended = () => {
          if (audio.current === el) stop()
        }
        await el.play()
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setError((e as Error).message)
          setSpeaking(false)
        }
      }
    },
    [stop],
  )

  useEffect(() => stop, [stop])

  return { speak, stop, speaking, error }
}
