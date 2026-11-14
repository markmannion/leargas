import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './ui/clar/ClarApp'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
