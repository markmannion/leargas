import type { Engine, Health } from '../types'

interface Props {
  engine: Engine
  onEngine: (e: Engine) => void
  health: Health | null
  healthError: boolean
}

const ENGINES: { id: Engine; label: string; title: string }[] = [
  { id: 'auto', label: 'Auto', title: 'Router: geometry when a vector twin exists, otherwise the fine-tuned model' },
  { id: 'geometry', label: 'Geometry', title: 'DXF / IFC geometry engine only' },
  { id: 'gemma_ft', label: 'Gemma FT', title: 'Fine-tuned Gemma only' },
  { id: 'gemma_base', label: 'Gemma base', title: 'Base Gemma only (the before number)' },
]

export function TopBar({ engine, onEngine, health, healthError }: Props) {
  const status = healthError ? 'offline' : !health ? 'connecting' : health.mode === 'mock' ? 'mock' : 'live'
  const statusText = {
    offline: 'API offline',
    connecting: 'Connecting…',
    mock: 'Mock API',
    live: 'Live API',
  }[status]

  return (
    <header className="topbar">
      <div className="brand">
        <img src="/hackjunction.png" alt="Junction" className="brand-logo" width={30} height={30} />
        <span className="brand-divider" aria-hidden />
        <span className="brand-name">Léargas</span>
        <span className="brand-product">BlueprintTrace</span>
      </div>

      <div className="topbar-right">
        <div className="engine">
          <span className="engine-label">Engine</span>
          <div className="seg dark" role="group" aria-label="Answer engine">
            {ENGINES.map((e) => (
              <button
                key={e.id}
                className={engine === e.id ? 'on' : undefined}
                onClick={() => onEngine(e.id)}
                title={e.title}
              >
                {e.label}
              </button>
            ))}
          </div>
        </div>
        <span className={`api-status ${status}`} title={health ? `${health.gold_questions_loaded} reference questions loaded` : undefined}>
          <span className="dot" />
          {statusText}
        </span>
      </div>
    </header>
  )
}
