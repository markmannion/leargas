import type { Evidence, Region } from '../../types'
import type { Viewport } from '../../core/viewport'
import { regionPath, shapeAnchor, shapePath } from '../../core/shapes'

interface Props {
  vp: Viewport
  evidence: Evidence[]
  lit: boolean
  hovered: number | null
  highlighted?: number[]
  onHover: (i: number | null) => void
  region: Region | null
  selecting: boolean
  dark: boolean
}

// The light's edge says how the mark was found: sharp for measured geometry, softer for text read
// off the sheet, softest for a model's estimate.
const BLUR = { sharp: 1.5, read: 5, soft: 11 }
function softness(e: Evidence): keyof typeof BLUR {
  if (e.source === 'gemma_ft' || e.source === 'gemma_base') return 'soft'
  if (e.source === 'sheet_reader') return 'read'
  return 'sharp'
}

export function SolasSheet({ vp, evidence, lit, hovered, highlighted, onHover, region, selecting, dark }: Props) {
  const { W, H, view, aspect } = vp
  const k = view.k
  const shown = selecting && vp.draft ? vp.draft : region
  const marks = lit ? evidence.map((e, i) => ({ e, i })).filter(({ e }) => (e.page ?? 0) === 0) : []
  const focus = hovered !== null ? new Set([hovered, ...(highlighted ?? [])]) : null
  const inLight = focus ? marks.filter(({ i }) => focus.has(i)) : marks
  // Darken the sheet when there is something to light, or a region to light while drawing it.
  const darken = dark && (inLight.length > 0 || Boolean(shown))

  return (
    <div ref={vp.frame} className={`so-frame${vp.dragging ? ' is-panning' : ''}${selecting ? ' is-boxing' : ''}`} {...vp.handlers}>
      {vp.imgProps.src && (
        <div className="so-sheet" style={vp.sheetStyle}>
          <img {...vp.imgProps} key={vp.imgProps.src} alt="Drawing sheet" />
          {aspect && (
            <svg className="so-svg" viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
              <defs>
                {Object.entries(BLUR).map(([name, sd]) => (
                  <filter key={name} id={`so-blur-${name}`} filterUnits="userSpaceOnUse" x={-W} y={-H} width={W * 3} height={H * 3}>
                    <feGaussianBlur stdDeviation={sd / k} />
                  </filter>
                ))}
                <mask id="so-mask" maskUnits="userSpaceOnUse" x={-W} y={-H} width={W * 3} height={H * 3}>
                  <rect x={-W} y={-H} width={W * 3} height={H * 3} fill="#fff" />
                  {inLight.map(({ e, i }) => {
                    return (
                      <g key={i} filter={`url(#so-blur-${softness(e)})`}>
                        {e.shape.kind === 'point'
                          ? <circle cx={e.shape.point[0] * W} cy={e.shape.point[1] * H} r={18 / k} fill="#000" />
                          : <path d={shapePath(e.shape, W, H)} fillRule="evenodd" fill="#000" stroke="#000" strokeWidth={10 / k} strokeLinejoin="round" />}
                      </g>
                    )
                  })}
                  {shown && inLight.length === 0 && <path d={regionPath(shown, W, H)} fill="#000" />}
                </mask>
              </defs>
              {darken && <rect className="so-dark" x={-W} y={-H} width={W * 3} height={H * 3} mask="url(#so-mask)" />}
              {shown && (
                <path d={regionPath(shown, W, H)} className="so-region" strokeWidth={1.5 / k} strokeDasharray={`${6 / k} ${4 / k}`} />
              )}
              {marks.map(({ e, i }) => {
                const on = focus?.has(i) ?? false
                const off = focus !== null && !on
                const [ax, ay] = shapeAnchor(e.shape)
                const cls = `so-mark${on ? ' is-on' : ''}${off ? ' is-off' : ''}`
                return (
                  <g key={i} className={cls} onPointerEnter={() => onHover(i)} onPointerLeave={() => onHover(null)}>
                    {e.shape.kind === 'point'
                      ? <circle cx={ax * W} cy={ay * H} r={6 / k} strokeWidth={1.6 / k} />
                      : <path d={shapePath(e.shape, W, H)} fillRule="evenodd" strokeWidth={(on ? 2.2 : 1.3) / k} />}
                    <g transform={`translate(${ax * W} ${ay * H})`}>
                      <circle r={8.5 / k} className="so-tag" />
                      <text y={3.4 / k} fontSize={9.5 / k} className="so-tag-t">{i + 1}</text>
                    </g>
                  </g>
                )
              })}
            </svg>
          )}
        </div>
      )}
      <div className="so-empty">
        {vp.state === 'idle' && <p>Choose a drawing to begin.</p>}
        {vp.state === 'loading' && <p>Loading the sheet</p>}
        {vp.state === 'error' && <p>This sheet could not be loaded. Is the backend running?</p>}
      </div>
    </div>
  )
}
