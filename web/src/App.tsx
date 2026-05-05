import { useState, useRef, useCallback } from 'react'
import {
  LayoutDashboard, Upload, History, Settings, HelpCircle,
  FileText, AlertCircle, CheckCircle, AlertTriangle,
  Download, Loader2, Layers,
} from 'lucide-react'

// ── Types ────────────────────────────────────────────────────
interface Issue {
  category: string
  severity: string
  description: string
  page: number
  location: string
  confidence: number
}
interface AnalysisResult {
  status: string
  pdf_pages: number
  summary: {
    total: number; errors: number; warnings: number; info: number
    by_category: { spell: number; bend: number; rebar: number }
  }
  issues: Issue[]
}
type AppState = 'idle' | 'ready' | 'analyzing' | 'done' | 'error'

// ── Constants ────────────────────────────────────────────────
const NODES = [
  { key: 'preprocess',        label: 'Extracting PDF content' },
  { key: 'spell_check',       label: 'Checking spelling & labels' },
  { key: 'bend_check',        label: 'Validating bending details' },
  { key: 'rebar_check',       label: 'Validating rebar specs' },
  { key: 'aggregate_results', label: 'Aggregating results' },
  { key: 'return_to_ui',      label: 'Preparing report' },
]
const NAV = [
  { icon: LayoutDashboard, label: 'Dashboard', active: true },
  { icon: Upload,          label: 'Uploads' },
  { icon: History,         label: 'Check History' },
  { icon: Settings,        label: 'Settings' },
]

// ── Helpers ──────────────────────────────────────────────────
function severityBadge(s: string) {
  if (s === 'error')   return { cls: 'bg-red-100 text-red-700 border border-red-200',     label: 'FAIL' }
  if (s === 'warning') return { cls: 'bg-amber-100 text-amber-700 border border-amber-200', label: 'WARN' }
  return                       { cls: 'bg-green-100 text-green-700 border border-green-200',  label: 'OK' }
}
function catBadge(c: string) {
  if (c === 'rebar') return 'bg-blue-100 text-blue-700'
  if (c === 'bend')  return 'bg-purple-100 text-purple-700'
  return                    'bg-gray-100 text-gray-500'
}

/** SSE handler sends AnalysisResult; some backends return JSON: { ok, filename, result: { spell: { issues }, ... } } */
function isAnalysisResultShape(x: unknown): x is AnalysisResult {
  if (!x || typeof x !== 'object') return false
  const o = x as Record<string, unknown>
  const s = o.summary
  return (
    typeof o.status === 'string' &&
    typeof o.pdf_pages === 'number' &&
    s != null &&
    typeof s === 'object' &&
    Array.isArray(o.issues)
  )
}

function normalizeAnalyzeJsonToResult(body: unknown): AnalysisResult | null {
  if (!body || typeof body !== 'object') return null
  const root = body as Record<string, unknown>

  const inner = root.result !== undefined ? root.result : root
  if (isAnalysisResultShape(inner)) return inner

  if (!inner || typeof inner !== 'object') return null
  const raw = inner as Record<string, unknown>

  const issues: Issue[] = []
  for (const cat of ['spell', 'bend', 'rebar'] as const) {
    const section = raw[cat]
    if (!section || typeof section !== 'object') continue
    const list = (section as { issues?: unknown }).issues
    if (!Array.isArray(list)) continue
    for (const item of list) {
      if (!item || typeof item !== 'object') continue
      const it = item as Record<string, unknown>
      const description =
        typeof it.message === 'string'
          ? it.message
          : typeof it.description === 'string'
            ? it.description
            : JSON.stringify(item)
      const location =
        typeof it.token === 'string'
          ? it.token
          : typeof it.location === 'string'
            ? it.location
            : ''
      const page = typeof it.page === 'number' ? it.page : 0
      const severity = typeof it.severity === 'string' ? it.severity : 'info'
      let confidence = 0.85
      if (typeof it.confidence === 'number') {
        confidence = it.confidence > 1 ? it.confidence / 100 : it.confidence
      }
      issues.push({ category: cat, severity, description, page, location, confidence })
    }
  }

  const pdfPages =
    typeof raw.pdf_pages === 'number'
      ? raw.pdf_pages
      : typeof root.pdf_pages === 'number'
        ? root.pdf_pages
        : 0

  if (issues.length === 0 && Array.isArray(raw.issues)) {
    for (const item of raw.issues) {
      if (!item || typeof item !== 'object') continue
      const it = item as Record<string, unknown>
      const cat = typeof it.category === 'string' ? it.category : 'spell'
      issues.push({
        category: cat,
        severity: typeof it.severity === 'string' ? it.severity : 'info',
        description: typeof it.description === 'string' ? it.description : String(it.message ?? ''),
        page: typeof it.page === 'number' ? it.page : 0,
        location: typeof it.location === 'string' ? it.location : '',
        confidence:
          typeof it.confidence === 'number'
            ? (it.confidence > 1 ? it.confidence / 100 : it.confidence)
            : 0.85,
      })
    }
  }

  const total = issues.length
  const errors = issues.filter((i) => i.severity === 'error').length
  const warnings = issues.filter((i) => i.severity === 'warning').length
  const info = issues.filter((i) => i.severity === 'info').length

  return {
    status: 'completed',
    pdf_pages: pdfPages,
    summary: {
      total,
      errors,
      warnings,
      info,
      by_category: {
        spell: issues.filter((i) => i.category === 'spell').length,
        bend: issues.filter((i) => i.category === 'bend').length,
        rebar: issues.filter((i) => i.category === 'rebar').length,
      },
    },
    issues,
  }
}

// ── Component ────────────────────────────────────────────────
export default function App() {
  const [appState, setAppState]         = useState<AppState>('idle')
  const [file, setFile]                 = useState<File | null>(null)
  const [result, setResult]             = useState<AnalysisResult | null>(null)
  const [errorMsg, setErrorMsg]         = useState('')
  const [isDragging, setIsDragging]     = useState(false)
  const [doneNodes, setDoneNodes]       = useState<string[]>([])
  const [activeNode, setActiveNode]     = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const pickFile = (f: File) => {
    if (!f.name.toLowerCase().endsWith('.pdf')) return
    setFile(f); setResult(null); setDoneNodes([]); setActiveNode(null)
    setAppState('ready')
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setIsDragging(false)
    const f = e.dataTransfer.files[0]; if (f) pickFile(f)
  }, [])

  const analyze = async () => {
    if (!file) return
    setAppState('analyzing'); setDoneNodes([]); setActiveNode(null); setResult(null)

    const form = new FormData()
    form.append('file', file)

    try {
      const res = await fetch('/api/analyze', { method: 'POST', body: form })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const contentType = res.headers.get('content-type') ?? ''
      if (contentType.includes('application/json')) {
        const text = await res.text()
        let parsed: unknown
        try {
          parsed = JSON.parse(text)
        } catch {
          throw new Error('Invalid JSON response from /api/analyze')
        }
        const root = parsed as Record<string, unknown>
        if (root.ok === false) {
          throw new Error(
            typeof root.message === 'string'
              ? root.message
              : typeof root.error === 'string'
                ? root.error
                : 'Analysis failed (ok: false)',
          )
        }
        const normalized = normalizeAnalyzeJsonToResult(parsed)
        if (!normalized) {
          const detail = root.detail ?? root.message
          throw new Error(
            typeof detail === 'string'
              ? detail
              : detail !== undefined
                ? JSON.stringify(detail).slice(0, 500)
                : 'Could not parse analyze JSON (unknown shape)',
          )
        }
        setResult(normalized)
        setDoneNodes(NODES.map((n) => n.key))
        setActiveNode(null)
        setAppState('done')
        return
      }

      if (!res.body) throw new Error('No response body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let receivedResult = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() ?? '' // keep incomplete last line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = JSON.parse(line.slice(6)) as {
            type?: string
            node?: string
            message?: string
            data?: AnalysisResult
          }

          if (payload.type === 'ack') {
            /* backend received file; optional UX hook */
          } else if (payload.type === 'progress') {
            setActiveNode(payload.node ?? null)
            setDoneNodes((prev) => [...prev, payload.node ?? ''])
          } else if (payload.type === 'result') {
            setResult(payload.data ?? null)
            setActiveNode(null)
            setAppState('done')
            receivedResult = true
          } else if (payload.type === 'error') {
            throw new Error(payload.message ?? 'Analysis failed')
          }
        }
      }

      if (!receivedResult) {
        throw new Error(
          'Stream ended without a result. Ensure /api/analyze returns SSE (text/event-stream) and the graph runs to return_to_ui.',
        )
      }
    } catch (err) {
      setErrorMsg(String(err))
      setAppState('error')
    }
  }

  const downloadReport = () => {
    if (!result) return
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    const a = Object.assign(document.createElement('a'), {
      href:     URL.createObjectURL(blob),
      download: `drawing_report_${file?.name ?? 'result'}.json`,
    })
    a.click(); URL.revokeObjectURL(a.href)
  }

  const progress = Math.round((doneNodes.length / NODES.length) * 100)
  const overall  = result
    ? result.summary.errors   > 0 ? 'FAIL'
    : result.summary.warnings > 0 ? 'WARN' : 'PASS'
    : null

  // ── Render ─────────────────────────────────────────────────
  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">

      {/* Sidebar */}
      <aside className="w-56 bg-slate-900 flex flex-col flex-shrink-0 shadow-xl">
        <div className="px-5 py-5 border-b border-slate-700">
          <div className="flex items-center gap-3">
            <div className="relative w-9 h-9 flex-shrink-0">
              <div className="absolute inset-0 rounded-md border-2 border-blue-500" />
              <div className="absolute inset-[5px] rounded border-2 border-blue-300" />
              <Layers size={10} className="absolute bottom-1 right-1 text-blue-400" />
            </div>
            <div>
              <p className="text-white font-extrabold text-xs tracking-widest leading-none">DRAWING</p>
              <p className="text-blue-400 font-extrabold text-xs tracking-widest leading-none mt-0.5">ANALYZER</p>
            </div>
          </div>
          <p className="text-slate-500 text-[10px] mt-2 tracking-wide">AI-powered QA Tool</p>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map(({ icon: Icon, label, active }) => (
            <button key={label}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                active ? 'bg-blue-600 text-white shadow' : 'text-slate-400 hover:bg-slate-800 hover:text-white'
              }`}
            >
              <Icon size={15} />{label}
            </button>
          ))}
        </nav>

        <div className="px-3 pb-5">
          <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800 hover:text-white transition-colors">
            <HelpCircle size={15} />Support
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b px-7 py-4 flex items-center justify-between flex-shrink-0">
          <h1 className="text-lg font-semibold text-gray-800">Dashboard</h1>
          <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-bold">P</div>
        </header>

        <div className="flex-1 overflow-y-auto p-7 space-y-6">

          {/* Upload + Active checks */}
          <div className="grid grid-cols-2 gap-6">

            {/* Drop zone */}
            <div
              onClick={() => inputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={onDrop}
              className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all select-none ${
                isDragging ? 'border-blue-400 bg-blue-50 scale-[1.01]' : 'border-gray-300 bg-white hover:border-blue-300 hover:bg-gray-50'
              }`}
            >
              <input ref={inputRef} type="file" accept=".pdf" className="hidden"
                onChange={e => e.target.files?.[0] && pickFile(e.target.files[0])} />
              <FileText size={52} className="mx-auto text-gray-300 mb-4" />
              <p className="font-bold text-gray-700 tracking-wide">DRAG & DROP BUILDING DRAWINGS HERE</p>
              <p className="text-xs text-gray-400 mt-1 tracking-widest">SUPPORTED FORMAT: PDF (GERMAN STANDARDS)</p>
              <button onClick={e => e.stopPropagation()}
                className="mt-5 px-5 py-2 bg-slate-700 text-white text-sm font-medium rounded-lg hover:bg-slate-800 transition-colors">
                SELECT FILES FROM COMPUTER
              </button>
            </div>

            {/* Active checks panel */}
            <div className="bg-white rounded-2xl border p-5 flex flex-col gap-4">
              <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest">Active Checks</h2>

              {!file ? (
                <div className="flex-1 flex items-center justify-center text-gray-300 text-sm">
                  No file selected
                </div>
              ) : (
                <>
                  {/* File row */}
                  <div className="border rounded-xl overflow-hidden">
                    <div className="flex items-center gap-3 px-4 py-3 bg-gray-50">
                      <FileText size={15} className="text-blue-500 flex-shrink-0" />
                      <span className="text-sm font-medium text-gray-700 truncate flex-1">{file.name}</span>

                      {appState === 'ready' && (
                        <>
                          <span className="text-[10px] bg-gray-200 text-gray-500 px-2 py-0.5 rounded-full font-medium">READY</span>
                          <button onClick={analyze}
                            className="ml-1 px-3 py-1.5 bg-blue-600 text-white text-xs font-semibold rounded-lg hover:bg-blue-700 transition-colors">
                            START CHECK
                          </button>
                        </>
                      )}
                      {appState === 'analyzing' && (
                        <span className="text-[10px] bg-blue-100 text-blue-600 px-2 py-0.5 rounded-full font-medium flex items-center gap-1">
                          <Loader2 size={9} className="animate-spin" /> ANALYZING
                        </span>
                      )}
                      {appState === 'done' && (
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                          overall === 'FAIL' ? 'bg-red-100 text-red-600' : 'bg-green-100 text-green-600'
                        }`}>
                          DONE · {result?.summary.errors ?? 0} ERRORS
                        </span>
                      )}
                      {appState === 'error' && (
                        <span className="text-[10px] bg-red-100 text-red-600 px-2 py-0.5 rounded-full font-medium">FAILED</span>
                      )}
                    </div>
                  </div>

                  {/* Progress area (only while analyzing) */}
                  {appState === 'analyzing' && (
                    <div className="space-y-3">
                      {/* Progress bar */}
                      <div>
                        <div className="flex justify-between text-xs text-gray-400 mb-1">
                          <span>Analyzing drawing…</span>
                          <span>{progress}%</span>
                        </div>
                        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 rounded-full transition-all duration-500"
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                      </div>

                      {/* Node checklist */}
                      <div className="space-y-1.5">
                        {NODES.map(node => {
                          const done    = doneNodes.includes(node.key)
                          const running = activeNode === node.key && !done
                          return (
                            <div key={node.key} className="flex items-center gap-2 text-xs">
                              {done ? (
                                <CheckCircle size={13} className="text-green-500 flex-shrink-0" />
                              ) : running ? (
                                <Loader2 size={13} className="text-blue-500 animate-spin flex-shrink-0" />
                              ) : (
                                <div className="w-[13px] h-[13px] rounded-full border border-gray-200 flex-shrink-0" />
                              )}
                              <span className={done ? 'text-gray-600' : running ? 'text-blue-600 font-medium' : 'text-gray-300'}>
                                {node.label}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Error */}
                  {appState === 'error' && (
                    <div className="text-sm text-red-600 bg-red-50 rounded-xl p-3 border border-red-100">
                      {errorMsg}
                    </div>
                  )}

                  {/* Done summary */}
                  {appState === 'done' && result && (
                    <div className="flex gap-4 text-xs text-gray-500 px-1">
                      <span className="text-red-500 font-medium">{result.summary.errors} errors</span>
                      <span className="text-amber-500 font-medium">{result.summary.warnings} warnings</span>
                      <span className="text-green-500 font-medium">{result.summary.info} OK</span>
                      <span className="ml-auto text-gray-400">{result.pdf_pages} page(s)</span>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Results table */}
          {result && (
            <div className="bg-white rounded-2xl border overflow-hidden shadow-sm">

              <div className="px-6 py-4 border-b flex items-center justify-between">
                <div>
                  <h2 className="font-bold text-gray-800 uppercase text-xs tracking-widest">
                    Drawing Analysis Results · {result.pdf_pages} page(s)
                  </h2>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Spell: {result.summary.by_category.spell} · Bend: {result.summary.by_category.bend} · Rebar: {result.summary.by_category.rebar}
                  </p>
                </div>
                <button onClick={downloadReport}
                  className="flex items-center gap-2 px-4 py-2 bg-slate-700 text-white text-sm font-medium rounded-xl hover:bg-slate-800 transition-colors">
                  <Download size={14} />Download Detailed Report
                </button>
              </div>

              {/* Summary strip */}
              <div className="px-6 py-3 bg-gray-50 border-b flex items-center gap-6 flex-wrap">
                <span className="flex items-center gap-1.5 text-sm text-gray-600">
                  <CheckCircle size={15} className="text-green-500" /><strong>{result.summary.info}</strong> OK
                </span>
                <span className="flex items-center gap-1.5 text-sm text-gray-600">
                  <AlertTriangle size={15} className="text-amber-500" /><strong>{result.summary.warnings}</strong> Warnings
                </span>
                <span className="flex items-center gap-1.5 text-sm text-gray-600">
                  <AlertCircle size={15} className="text-red-500" /><strong>{result.summary.errors}</strong> Errors
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <span className="text-xs text-gray-400">Overall:</span>
                  <span className={`px-3 py-1 rounded-full text-xs font-bold tracking-wide ${
                    overall === 'FAIL' ? 'bg-red-100 text-red-700' :
                    overall === 'WARN' ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'
                  }`}>{overall}</span>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b text-[11px] font-bold text-gray-400 uppercase tracking-wider">
                      <th className="px-5 py-3 text-left w-10">#</th>
                      <th className="px-5 py-3 text-left">Category</th>
                      <th className="px-5 py-3 text-left">Page</th>
                      <th className="px-5 py-3 text-left">Location</th>
                      <th className="px-5 py-3 text-left">Confidence</th>
                      <th className="px-5 py-3 text-left">Status</th>
                      <th className="px-5 py-3 text-left">Issue / Remark</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {result.issues.map((issue, i) => {
                      const { cls, label } = severityBadge(issue.severity)
                      return (
                        <tr key={i} className="hover:bg-gray-50 transition-colors">
                          <td className="px-5 py-3 text-gray-300 font-mono text-xs">{String(i + 1).padStart(3, '0')}</td>
                          <td className="px-5 py-3">
                            <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase ${catBadge(issue.category)}`}>
                              {issue.category}
                            </span>
                          </td>
                          <td className="px-5 py-3 text-gray-500">{issue.page}</td>
                          <td className="px-5 py-3 text-gray-500 max-w-[140px] truncate" title={issue.location}>
                            {issue.location}
                          </td>
                          <td className="px-5 py-3 text-gray-500">{Math.round(issue.confidence * 100)}%</td>
                          <td className="px-5 py-3">
                            <span className={`px-2.5 py-0.5 rounded text-[11px] font-bold ${cls}`}>{label}</span>
                          </td>
                          <td className="px-5 py-3 text-gray-700 max-w-sm text-xs leading-relaxed">{issue.description}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              <div className="px-6 py-3 border-t bg-gray-50 flex items-center gap-6 text-xs text-gray-500">
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-green-500" />PASS
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-red-500" />FAIL
                </span>
                <span className="ml-2">
                  Checked {result.summary.total} issues · <strong>{result.summary.total - result.summary.errors}</strong> passed · <strong className="text-red-600">{result.summary.errors}</strong> failed.
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
