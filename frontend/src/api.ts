import type { Answer, AskRequest, Drawing, Health } from './types'

// In dev, Vite proxies /api to the FastAPI app (see vite.config.ts).
export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body = await res.text().catch(() => '')
    // FastAPI errors are {"detail": "..."}; show the message, not the raw JSON.
    try {
      const d = (JSON.parse(body) as { detail?: unknown }).detail
      if (d !== undefined) body = typeof d === 'string' ? d : JSON.stringify(d)
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status} ${res.statusText}${body ? ` — ${body.slice(0, 200)}` : ''}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => fetch(`${API_BASE}/health`).then((r) => json<Health>(r)),

  drawings: async () => {
    const all: Drawing[] = []
    let total = 0
    do {
      const page = await fetch(`${API_BASE}/drawings?limit=5000&offset=${all.length}`)
        .then((r) => json<{ total: number; drawings: Drawing[] }>(r))
      total = page.total
      all.push(...page.drawings)
      if (!page.drawings.length) break
    } while (all.length < total)
    return { total, drawings: all }
  },

  ask: (req: AskRequest, signal?: AbortSignal) =>
    fetch(`${API_BASE}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
      signal,
    }).then((r) => json<Answer>(r)),

  upload: (file: File, onProgress: (percent: number) => void): Promise<Drawing> =>
    new Promise((resolve, reject) => {
      const request = new XMLHttpRequest()
      request.open('POST', `${API_BASE}/drawings/upload?filename=${encodeURIComponent(file.name)}`)
      request.setRequestHeader('Content-Type', 'application/octet-stream')
      request.timeout = 120000
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100))
      }
      request.onload = () => {
        json<Drawing>(new Response(request.responseText, { status: request.status, statusText: request.statusText }))
          .then(resolve, reject)
      }
      request.onerror = () => reject(new Error('Could not reach the server. Check your connection and try again.'))
      request.ontimeout = () => reject(new Error('Upload timed out. Try a smaller file or check the plan library before retrying.'))
      request.send(file)
    }),

  drawingUrl: (path: string, page = 0) =>
    `${API_BASE}/drawing?path=${encodeURIComponent(path)}&page=${page}`,
}
