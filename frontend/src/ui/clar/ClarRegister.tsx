import { Fragment, useEffect, useRef, useState } from 'react'
import type { Drawing } from '../../types'
import { collectionName, drawingName, formatsOf, useCatalogue } from '../../core/catalogue'
import { UPLOAD_ACCEPT, useUpload } from '../../core/upload'

interface Props {
  drawings: Drawing[]
  selected: string | null
  loading: boolean
  error: string | null
  onSelect: (d: Drawing) => void
  onUploaded: (d: Drawing[]) => void
  onClose: () => void
}

const PAGE = 150

/** The drawing register: the list of every sheet in the set, as issued with a drawing package. */
export function ClarRegister({ drawings, selected, loading, error, onSelect, onUploaded, onClose }: Props) {
  const c = useCatalogue(drawings)
  const [limit, setLimit] = useState(PAGE)
  const [over, setOver] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const search = useRef<HTMLInputElement>(null)
  const up = useUpload((d) => { c.clear(); onUploaded(d) })
  const rows = c.results.slice(0, limit)
  // Uploads come first; label the two groups when the list has uploads in it.
  const grouped = rows.some((d) => d.collection === 'uploads')
  const width = String(c.results.length).length

  useEffect(() => { search.current?.focus() }, [])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  return (
    <div className={`cr${over ? ' is-over' : ''}`} role="dialog" aria-modal="true" aria-label="Drawing register"
      onDragOver={(e) => { e.preventDefault(); setOver(true) }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false) }}
      onDrop={(e) => { e.preventDefault(); setOver(false); void up.upload(e.dataTransfer.files) }}>
      <header className="cr-head">
        <h2>Drawing register</h2>
        <p className="cr-count">
          {loading ? 'Loading…' : c.filtered ? `${c.results.length.toLocaleString()} of ${drawings.length.toLocaleString()}` : `${drawings.length.toLocaleString()} sheets`}
        </p>
        <button type="button" className="cr-close" onClick={onClose}>Close <kbd>Esc</kbd></button>
      </header>

      <div className="cr-filters">
        <label className="cr-search">
          <span>Find</span>
          <input ref={search} type="search" value={c.query} placeholder="site, building, floor or file name"
            onChange={(e) => { c.setQuery(e.target.value); setLimit(PAGE) }}
            onKeyDown={(e) => { if (e.key === 'Enter' && c.results[0]) { e.preventDefault(); onSelect(c.results[0]) } }} />
        </label>
        <label className="cr-field">
          <span>Set</span>
          <select value={c.collection} onChange={(e) => { c.setCollection(e.target.value); setLimit(PAGE) }}>
            <option value="">All</option>
            {c.collections.map(([name, n]) => <option key={name} value={name}>{collectionName(name)} ({n.toLocaleString()})</option>)}
          </select>
        </label>
        {c.formats.length > 1 && (
          <fieldset className="cr-formats">
            <legend>Format</legend>
            {['', ...c.formats].map((f) => (
              <button key={f || 'all'} type="button" aria-pressed={c.format === f} onClick={() => { c.setFormat(f); setLimit(PAGE) }}>
                {f || 'All'}
              </button>
            ))}
          </fieldset>
        )}
        <div className="cr-add">
          <input ref={file} type="file" hidden multiple accept={UPLOAD_ACCEPT}
            onChange={(e) => { void up.upload(e.currentTarget.files); e.currentTarget.value = '' }} />
          <button type="button" disabled={up.busy} onClick={() => file.current?.click()}>
            {up.busy ? (up.progress === 100 ? 'Preparing…' : `Adding ${up.progress}%`) : 'Add drawings'}
          </button>
        </div>
      </div>

      <div className="cr-body">
        {error && <p className="cr-msg">The register could not be loaded: {error}</p>}
        {!error && !loading && c.results.length === 0 && (
          <p className="cr-msg">{drawings.length ? 'No sheet matches.' : 'The register is empty. Add a drawing to start.'}
            {c.filtered && <button type="button" onClick={c.clear}>Clear the filters</button>}</p>
        )}
        {rows.length > 0 && (
          <table className="cr-table">
            <thead>
              <tr>
                <th scope="col" className="n">No.</th>
                <th scope="col">Title</th>
                <th scope="col">Set</th>
                <th scope="col">Format</th>
                <th scope="col" className="n">Questions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d, i) => {
                const [main, sub] = drawingName(d.name)
                const upload = d.collection === 'uploads'
                const heading = grouped && (i === 0 || upload !== (rows[i - 1].collection === 'uploads'))
                return (
                  <Fragment key={d.path}>
                  {heading && (
                    <tr className="cr-group"><th scope="rowgroup" colSpan={5}>{upload ? 'Uploaded files' : 'Dataset drawings'}</th></tr>
                  )}
                  <tr aria-current={d.path === selected ? 'true' : undefined}>
                    <td className="n cr-no">{String(i + 1).padStart(width, '0')}</td>
                    <th scope="row">
                      <button type="button" onClick={() => onSelect(d)} title={d.path}>
                        {main}{sub && <span>{sub}</span>}
                      </button>
                    </th>
                    <td>{collectionName(d.collection)}</td>
                    <td>{formatsOf(d).join(' + ')}</td>
                    <td className="n">{upload ? <span className="cr-dim">—</span> : d.questions.length}</td>
                  </tr>
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
        {c.results.length > limit && (
          <button type="button" className="cr-more" onClick={() => setLimit((n) => n + PAGE)}>
            Show the next {Math.min(PAGE, c.results.length - limit)} ({limit.toLocaleString()} of {c.results.length.toLocaleString()} shown)
          </button>
        )}
      </div>

      <footer className="cr-foot" role="status">
        {up.error ? <span className="cr-err">{up.error}</span>
          : up.message ? up.message
            : over ? 'Drop to add these files to the register.'
              : 'Drop PDF, PNG, JPEG, DXF or IFC files here, 25 MB each. Files with the same name are paired, so plan.pdf with plan.dxf is checked against the DXF.'}
      </footer>
    </div>
  )
}
