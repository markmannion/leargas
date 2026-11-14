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
    <header className="topbar glass">
      <div className="brand">
        <img src="/hackjunction.png" alt="Junction" className="brand-logo" width={28} height={28} />
        <div className="brand-text">
          <span className="brand-name">Léargas</span>
          <span className="brand-product">BlueprintTrace</span>
        </div>
      </div>

      <div className="doc-title">
        <span className="doc-name">{title ?? 'No drawing'}</span>
        {subtitle && <span className="doc-sub">{subtitle}</span>}
      </div>

      <div className="topbar-right">
        <div className="seg" role="radiogroup" aria-label="Answer engine">
          {ENGINES.map((e) => (
            <button
              key={e.id}
              role="radio"
              aria-checked={engine === e.id}
              className={engine === e.id ? 'on' : undefined}
              onClick={() => onEngine(e.id)}
              title={e.title}
            >
              {e.label}
            </button>
          ))}
        </div>
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
