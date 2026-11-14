import { useRef, useState } from 'react'
import { api } from '../api'
import type { Drawing } from '../types'

export function PlanUpload({ onUploaded }: { onUploaded: (drawings: Drawing[]) => void }) {
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
    const selected = Array.from(files)
    for (const file of selected) {
      if (!/\.(pdf|png|jpe?g|dxf|ifc)$/i.test(file.name)) {
        setError('Choose PDF, PNG, JPEG, DXF or IFC plans.'); return
      }
      if (!file.size) { setError(`${file.name} is empty. Choose another plan.`); return }
      if (file.size > 25 * 1024 * 1024) { setError('Each plan must be 25 MB or smaller.'); return }
    }
    active.current = true
    setBusy(true)
    setProgress(0)
    const uploaded = new Map<string, Drawing>()
    try {
      if (selected.length === 1 && !/\.ifc$/i.test(selected[0].name)) {
        const drawing = await api.upload(selected[0], setProgress)
        uploaded.set(drawing.name, drawing)
      } else {
        let group: string | undefined
        for (const [index, file] of selected.entries()) {
          const result = await api.uploadGroup(file, group, (percent) => {
            setProgress(Math.round((index * 100 + percent) / selected.length))
          })
          group = result.group
          // A PDF and its DXF share one plan entry, regardless of upload order.
          uploaded.set(result.drawing.name, result.drawing)
        }
      }
      onUploaded([...uploaded.values()])
      setMessage(`${uploaded.size === 1 ? 'Plan uploaded.' : `${uploaded.size} plans uploaded.`} Ready to explore.`)
    } catch (cause) {
      if (uploaded.size) onUploaded([...uploaded.values()])
      const reason = cause instanceof Error ? cause.message : 'Upload failed. Please try again.'
      setError(`${uploaded.size ? 'Earlier files were saved. ' : ''}${reason}`)
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
      <input ref={input} type="file" hidden multiple accept=".pdf,.png,.jpg,.jpeg,.dxf,.ifc"
        onChange={(event) => { void upload(event.currentTarget.files); event.currentTarget.value = '' }} />
      <button type="button" className="plan-upload-button" disabled={busy} onClick={() => input.current?.click()}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" />
        </svg>
        {busy ? progress === 100 ? 'Preparing plans…' : `Uploading… ${progress}%` : 'Upload plans'}
      </button>
      <p className="plan-upload-help">{dragging ? 'Drop your plans here' : 'or drop here · PDF, PNG, JPEG, DXF, IFC · 25 MB each'}</p>
      <p className="plan-upload-help">Select matching PDF and DXF files together to pair them.</p>
      {busy && <progress aria-label="Plan upload progress" value={progress} max={100} />}
      {error && <p className="plan-upload-error" role="alert">{error}</p>}
      <span className="plan-upload-status" role="status">{message}</span>
    </div>
  )
}
