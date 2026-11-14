import { StrictMode, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'

// Clár (the drawing-sheet layout) is the UI. ?ui=classic loads the earlier floating-panel UI as a
// fallback. Each brings its own stylesheet, and only the chosen one is loaded.
const ui = new URLSearchParams(location.search).get('ui')
const load: () => Promise<{ default: ComponentType }> =
  ui === 'classic' ? () => import('./original') : () => import('./ui/clar/ClarApp')

void load().then(({ default: App }) => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
