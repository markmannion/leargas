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

  drawings: (limit = 2000) =>
    fetch(`${API_BASE}/drawings?limit=${limit}`).then((r) => json<{ total: number; drawings: Drawing[] }>(r)),

  ask: (req: AskRequest, signal?: AbortSignal) =>
    fetch(`${API_BASE}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
      signal,
    }).then((r) => json<Answer>(r)),

  drawingUrl: (path: string, page = 0) =>
    `${API_BASE}/drawing?path=${encodeURIComponent(path)}&page=${page}`,
}
