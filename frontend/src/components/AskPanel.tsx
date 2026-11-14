import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Drawing } from '../types'
import { guessLang } from '../format'
import { useVoiceInput } from '../voice'

interface Props {
  drawing: Drawing | null
  busy: boolean
  onAsk: (question: string, spoken?: boolean) => void
  voice: boolean
  speaking: boolean
  voiceError: string | null
  onInterrupt: () => void
  children?: ReactNode
}

export function AskPanel({ drawing, busy, onAsk, voice, speaking, voiceError, onInterrupt, children }: Props) {
  const [text, setText] = useState('')
  const [conversation, setConversation] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const mic = useVoiceInput((question) => {
    setText(question)
    onAsk(question, true)
  })
  const { start, cancel } = mic
  const error = mic.error || voiceError
  const questions = useMemo(() => {
    const all = drawing?.questions ?? []
    return [...all].sort((a, b) => Number(guessLang(b.question) === 'EN') - Number(guessLang(a.question) === 'EN'))
  }, [drawing])

  // Half-duplex turns keep the assistant's own answer out of the microphone.
  useEffect(() => {
    if (!conversation || busy || speaking || error || mic.state !== 'idle') return
    const timer = setTimeout(() => void start(), 350)
    return () => clearTimeout(timer)
  }, [conversation, busy, speaking, error, mic.state, start])

  useEffect(() => {
    const pause = () => {
      if (document.hidden) { setConversation(false); cancel(); onInterrupt() }
    }
    document.addEventListener('visibilitychange', pause)
    return () => document.removeEventListener('visibilitychange', pause)
  }, [cancel, onInterrupt])

  const endVoice = () => { setConversation(false); cancel(); onInterrupt() }
  const startVoice = () => {
    onInterrupt()
    setConversation(true)
    void start()
  }
  const submit = (question: string) => {
    if (!question.trim() || !drawing || busy) return
    endVoice()
    setText(question.trim())
    onAsk(question.trim())
  }
  const active = conversation && !error
  const status = !active ? 'Talk about this drawing'
    : mic.state === 'requesting' ? 'Allow your microphone'
    : mic.state === 'transcribing' ? 'Getting your question…'
    : busy ? 'Checking the drawing…'
    : speaking ? 'Reading the answer…' : 'I’m listening'

  return (
    <section className="ask">
      <div className="inspector-head">
        <span className="eyebrow">On this sheet</span>
        <h1>Let’s take a closer look.</h1>
        <p>Ask a question. Follow the evidence.</p>
      </div>
      {voice && (
        <div className={`voice-box${active ? ' active' : ''}`}>
          <button type="button" className="voice-main" onClick={active ? endVoice : startVoice} disabled={!drawing}
            aria-pressed={active} aria-label={active ? 'End voice conversation' : 'Start voice conversation'}>
            <span className="voice-symbol">
              {active ? <span className="voice-bars" aria-hidden="true">{[0.5, 1, 0.7, 1, 0.5].map((factor, i) => <i key={i} style={{ height: `${5 + mic.level * 28 * factor}px` }} />)}</span> : <MicIcon />}
            </span>
            <span className="voice-copy"><strong role="status">{status}</strong><span>{active ? 'Pause when you’re done. I’ll take it from there.' : 'A conversation, with the plan in front of you.'}</span></span>
            {active && <span className="voice-end" aria-hidden="true">×</span>}
          </button>
          {active && (speaking || busy || mic.state === 'recording') && (
            <button type="button" className="voice-shortcut" onClick={speaking || busy ? () => { onInterrupt(); void start() } : mic.finish}>
              {speaking || busy ? 'Interrupt & ask something else' : 'Done speaking'} <span aria-hidden="true">↵</span>
            </button>
          )}
        </div>
      )}
      {error && <p className="voice-error" role="alert">{error}</p>}
      <form className="ask-form" onSubmit={(e) => { e.preventDefault(); submit(text) }}>
        <label htmlFor="question" className="field-label">{voice ? 'Or write a question' : 'Your question'}</label>
        <div className="question-input">
          <textarea id="question" rows={3} value={text} placeholder={drawing ? 'How many windows are on this floor?' : 'Choose a drawing to get started'}
            disabled={!drawing} onChange={(e) => { if (conversation) endVoice(); setText(e.target.value) }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(text) } }} />
          <div className="ask-actions"><span>Any language · Enter to ask</span><button type="submit" className="primary" disabled={!drawing || busy || !text.trim()}>{busy ? 'Checking…' : 'Ask'} <span aria-hidden="true">↗</span></button></div>
        </div>
      </form>
      {children}
      {questions.length > 0 && (
        <div className="suggestions block">
          <h3 className="block-title">A place to start</h3>
          <ul className="question-list">{(expanded ? questions : questions.slice(0, 3)).map((q, i) => (
            <li key={i}><button type="button" onClick={() => submit(q.question)} disabled={busy}><span>{q.question}</span><span aria-hidden="true">↗</span></button></li>
          ))}</ul>
          {questions.length > 3 && <button type="button" className="more-questions" onClick={() => setExpanded(!expanded)}>{expanded ? 'Show fewer' : `More questions (${questions.length - 3})`}</button>}
        </div>
      )}
    </section>
  )
}

function MicIcon() {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" /></svg>
}
