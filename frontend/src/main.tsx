import { StrictMode, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'

// Pick a UI with ?ui=: clar (drawing-sheet layout) or solas (lit-evidence layout). With no ?ui=,
// the original UI loads. Each UI brings its own stylesheet, and only the chosen one is loaded.
const ui = new URLSearchParams(location.search).get('ui')
const load: () => Promise<{ default: ComponentType }> =
  ui === 'clar' ? () => import('./ui/clar/ClarApp')
    : ui === 'solas' ? () => import('./ui/solas/SolasApp')
      : () => import('./original')

void load().then(({ default: App }) => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
