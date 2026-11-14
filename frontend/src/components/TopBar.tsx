import type { Engine, Health } from '../types'

interface Props {
  engine: Engine
  onEngine: (e: Engine) => void
  health: Health | null
  healthError: boolean
  title: string | null
  subtitle: string | null
}

const ENGINES: { id: Engine; label: string; title: string }[] = [
  { id: 'auto', label: 'Auto', title: 'Router: geometry when a vector twin exists, otherwise the fine-tuned model' },
  { id: 'geometry', label: 'Geometry', title: 'DXF / IFC geometry engine only' },
  { id: 'gemma_ft', label: 'Gemma FT', title: 'Fine-tuned Gemma only' },
  { id: 'gemma_base', label: 'Gemma Base', title: 'Base Gemma only (the before number)' },
]

export function TopBar({ engine, onEngine, health, healthError, title, subtitle }: Props) {
  const status = healthError ? 'offline' : !health ? 'connecting' : health.mode === 'mock' ? 'mock' : 'live'
  const statusText = {
    offline: 'Offline',
    connecting: 'Connecting',
    mock: 'Mock API',
    live: 'Live',
  }[status]

  return (
    <header className="topbar">
      <div className="brand">
        <svg className="brand-mark" viewBox="0 0 32 32" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M6 5v22h21M12 5v16h15M18 5v10h9" /><path d="M5 5h22v22" opacity=".35" /></svg>
        <div className="brand-text">
          <span className="brand-name">Léargas</span>
          <span className="brand-product">Drawing workspace</span>
        </div>
      </div>

      <div className="doc-title">
        <span className="doc-name">{title ?? 'No drawing'}</span>
        {subtitle && <span className="doc-sub">{subtitle}</span>}
      </div>

      <div className="topbar-right">
        <label className="engine-control">
          <span>Answer with</span>
          <select value={engine} onChange={(e) => onEngine(e.target.value as Engine)} aria-label="Answer engine">
            {ENGINES.map((e) => <option key={e.id} value={e.id}>{e.id === 'auto' ? 'Automatic' : e.label}</option>)}
          </select>
        </label>
        <span
          className={`api-status ${status}`}
          title={health ? `${health.gold_questions_loaded.toLocaleString()} reference questions loaded` : undefined}
        >
          <span className="dot" />
          {statusText}
        </span>
      </div>
    </header>
  )
}
