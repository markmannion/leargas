import { useRef, useState } from 'react'
import { api } from '../api'
import type { Drawing } from '../types'

export const UPLOAD_ACCEPT = '.pdf,.png,.jpg,.jpeg,.dxf,.ifc'

/** Same rules as components/PlanUpload: one file goes to /drawings/upload, a set is paired by group. */
export function useUpload(onUploaded: (drawings: Drawing[]) => void) {
  const active = useRef(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  async function upload(files: FileList | File[] | null) {
    if (!files || !files.length || active.current) return
    setError(null)
    setMessage('')
    const list = Array.from(files)
    for (const f of list) {
      if (!/\.(pdf|png|jpe?g|dxf|ifc)$/i.test(f.name)) return setError(`${f.name}: use PDF, PNG, JPEG, DXF or IFC.`)
      if (!f.size) return setError(`${f.name} is empty.`)
      if (f.size > 25 * 1024 * 1024) return setError(`${f.name} is over 25 MB.`)
    }
    active.current = true
    setBusy(true)
    setProgress(0)
    const done = new Map<string, Drawing>()
    try {
      if (list.length === 1 && !/\.ifc$/i.test(list[0].name)) {
        const d = await api.upload(list[0], setProgress)
        done.set(d.name, d)
      } else {
        let group: string | undefined
        for (const [i, f] of list.entries()) {
          const r = await api.uploadGroup(f, group, (p) => setProgress(Math.round((i * 100 + p) / list.length)))
          group = r.group
          done.set(r.drawing.name, r.drawing)
        }
      }
      onUploaded([...done.values()])
      setMessage(done.size === 1 ? 'Added.' : `${done.size} drawings added.`)
    } catch (cause) {
      if (done.size) onUploaded([...done.values()])
      const why = cause instanceof Error ? cause.message : 'Upload failed.'
      setError(`${done.size ? 'The first files were saved. ' : ''}${why}`)
    } finally {
      active.current = false
      setBusy(false)
    }
  }

  return { upload, busy, progress, error, message }
}
