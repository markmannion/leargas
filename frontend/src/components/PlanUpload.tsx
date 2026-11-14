import { useRef, useState } from 'react'
import { api } from '../api'
import type { Drawing } from '../types'

export function PlanUpload({ onUploaded }: { onUploaded: (drawing: Drawing) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const active = useRef(false)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  async function upload(files: FileList | null) {
    if (!files?.length || active.current) return
    setError(null)
    setMessage('')
    const file = files[0]
    if (files.length > 1) { setError('Upload one plan at a time.'); return }
    if (!/\.(pdf|png|jpe?g|dxf)$/i.test(file.name)) {
      setError('Choose a PDF, PNG, JPEG or DXF plan.'); return
    }
    if (!file.size) { setError('This file is empty. Choose another plan.'); return }
    if (file.size > 25 * 1024 * 1024) { setError('Plans must be 25 MB or smaller.'); return }
    active.current = true
    setBusy(true)
    setProgress(0)
    try {
      const drawing = await api.upload(file, setProgress)
      onUploaded(drawing)
      setMessage(`${file.name} uploaded. Ready to explore.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Upload failed. Please try again.')
    } finally {
      active.current = false
      setBusy(false)
    }
  }

  return (
    <div className={`plan-upload${dragging ? ' dragging' : ''}`} aria-busy={busy}
      onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true) }}
      onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
      onDrop={(event) => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files) }}>
      <input ref={input} type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.dxf"
        onChange={(event) => { void upload(event.currentTarget.files); event.currentTarget.value = '' }} />
      <button type="button" className="plan-upload-button" disabled={busy} onClick={() => input.current?.click()}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" />
        </svg>
        {busy ? progress === 100 ? 'Preparing plan…' : `Uploading… ${progress}%` : 'Upload a plan'}
      </button>
      <p className="plan-upload-help">{dragging ? 'Drop your plan here' : 'or drop here · PDF, PNG, JPEG, DXF · 25 MB'}</p>
      {busy && <progress aria-label="Plan upload progress" value={progress} max={100} />}
      {error && <p className="plan-upload-error" role="alert">{error}</p>}
      <span className="plan-upload-status" role="status">{message}</span>
    </div>
  )
}
