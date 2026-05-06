import { useState, useRef, useCallback } from 'react'
import {
  LayoutDashboard, Upload, History, Settings, HelpCircle,
  FileText, AlertCircle, CheckCircle, AlertTriangle,
  Download, Loader2, ChevronLeft, ChevronRight,
} from 'lucide-react'

// ── Types ────────────────────────────────────────────────────
interface Issue {
  id: string
  category: string
  severity: string   // "ERROR" | "WARNING" | "INFO"
  description: string
  page: number
  location: string
  confidence: number
}
interface Section {
  category: string
  title: string
  count: number
  issues: Issue[]
}
interface AnalysisResult {
  status: string
  message: string
  pdf_pages: number
  summary: { total: number; ERROR: number; WARNING: number; INFO: number }
  sections: Section[]
}
type AppState = 'idle' | 'ready' | 'analyzing' | 'done' | 'error'

// ── Constants ────────────────────────────────────────────────
const NODES = [
  { key: 'preprocess',        label: 'Extracting PDF content',      checkKey: null },
  { key: 'spell_check',       label: 'Checking spelling & labels',  checkKey: 'spell' },
  { key: 'bend_check',        label: 'Validating bending details',  checkKey: 'bend' },
  { key: 'rebar_check',       label: 'Validating rebar specs',      checkKey: 'rebar' },
  { key: 'aggregate_results', label: 'Aggregating results',         checkKey: null },
  { key: 'return_to_ui',      label: 'Preparing report',            checkKey: null },
]

const CHECK_OPTIONS = [
  { key: 'spell', label: 'Spelling & Labels',   color: 'gray' },
  { key: 'bend',  label: 'Bending & Schedule',  color: 'purple' },
  { key: 'rebar', label: 'Rebar Specs',          color: 'blue' },
] as const
const NAV = [
  { icon: LayoutDashboard, label: 'Dashboard', active: true },
  { icon: Upload,          label: 'Uploads' },
  { icon: History,         label: 'Check History' },
  { icon: Settings,        label: 'Settings' },
]

// ── Helpers ──────────────────────────────────────────────────
function severityBadge(s: string) {
  if (s === 'ERROR')   return { cls: 'bg-red-100 text-red-700 border border-red-200',      label: 'FAIL' }
  if (s === 'WARNING') return { cls: 'bg-amber-100 text-amber-700 border border-amber-200', label: 'WARN' }
  return                       { cls: 'bg-green-100 text-green-700 border border-green-200', label: 'OK' }
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
    typeof o.message === 'string' &&
    typeof o.pdf_pages === 'number' &&
    s != null &&
    typeof s === 'object' &&
    Array.isArray(o.sections)
  )
}

const _CAT_ORDER = ['bend', 'rebar', 'spell'] as const
const _CAT_TITLES: Record<string, string> = {
  spell: 'Drawing Labels & Annotation',
  bend:  'Bending & Bar Schedule',
  rebar: 'Rebar Labels & Dimensions',
}

function normalizeSeverity(s: unknown): string {
  const up = typeof s === 'string' ? s.toUpperCase() : 'INFO'
  return ['ERROR', 'WARNING', 'INFO'].includes(up) ? up : 'INFO'
}

function normalizeAnalyzeJsonToResult(body: unknown): AnalysisResult | null {
  if (!body || typeof body !== 'object') return null
  const root = body as Record<string, unknown>

  const inner = root.result !== undefined ? root.result : root
  if (isAnalysisResultShape(inner)) return inner

  if (!inner || typeof inner !== 'object') return null
  const raw = inner as Record<string, unknown>

  const rawIssues: Omit<Issue, 'id'>[] = []

  for (const cat of _CAT_ORDER) {
    const section = raw[cat]
    if (!section || typeof section !== 'object') continue
    const list = (section as { issues?: unknown }).issues
    if (!Array.isArray(list)) continue
    for (const item of list) {
      if (!item || typeof item !== 'object') continue
      const it = item as Record<string, unknown>
      rawIssues.push({
        category: cat,
        severity: normalizeSeverity(it.severity),
        description:
          typeof it.message === 'string' ? it.message
          : typeof it.description === 'string' ? it.description
          : JSON.stringify(item),
        page: typeof it.page === 'number' ? it.page : 0,
        location:
          typeof it.token === 'string' ? it.token
          : typeof it.location === 'string' ? it.location
          : '',
        confidence: typeof it.confidence === 'number'
          ? (it.confidence > 1 ? it.confidence / 100 : it.confidence)
          : 0.85,
      })
    }
  }

  if (rawIssues.length === 0 && Array.isArray(raw.issues)) {
    for (const item of raw.issues) {
      if (!item || typeof item !== 'object') continue
      const it = item as Record<string, unknown>
      rawIssues.push({
        category: typeof it.category === 'string' ? it.category : 'spell',
        severity: normalizeSeverity(it.severity),
        description: typeof it.description === 'string' ? it.description : String(it.message ?? ''),
        page: typeof it.page === 'number' ? it.page : 0,
        location: typeof it.location === 'string' ? it.location : '',
        confidence: typeof it.confidence === 'number'
          ? (it.confidence > 1 ? it.confidence / 100 : it.confidence)
          : 0.85,
      })
    }
  }

  const pdfPages =
    typeof raw.pdf_pages === 'number' ? raw.pdf_pages
    : typeof root.pdf_pages === 'number' ? root.pdf_pages
    : 0

  // Assign sequential IDs per category
  const catCounters: Record<string, number> = {}
  const issues: Issue[] = rawIssues.map(issue => {
    const cat = issue.category
    catCounters[cat] = (catCounters[cat] ?? 0) + 1
    return { ...issue, id: `${cat.toUpperCase()}-${String(catCounters[cat]).padStart(3, '0')}` }
  })

  const byCategory: Record<string, Issue[]> = {}
  for (const issue of issues) {
    if (!byCategory[issue.category]) byCategory[issue.category] = []
    byCategory[issue.category].push(issue)
  }

  const sections: Section[] = _CAT_ORDER
    .filter(cat => (byCategory[cat]?.length ?? 0) > 0)
    .map(cat => ({
      category: cat,
      title: _CAT_TITLES[cat] ?? cat,
      count: byCategory[cat].length,
      issues: byCategory[cat],
    }))

  const total   = issues.length
  const ERROR   = issues.filter(i => i.severity === 'ERROR').length
  const WARNING = issues.filter(i => i.severity === 'WARNING').length
  const INFO    = issues.filter(i => i.severity === 'INFO').length

  return {
    status: 'completed',
    message: total === 0
      ? 'No QA issues found. Drawing is clean.'
      : `Analysis completed. Found ${total} issue(s): ${ERROR} error, ${WARNING} warning, ${INFO} info.`,
    pdf_pages: pdfPages,
    summary: { total, ERROR, WARNING, INFO },
    sections,
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
  const [sidebarOpen, setSidebarOpen]   = useState(true)
  const [enabledChecks, setEnabledChecks] = useState<string[]>(['spell', 'bend', 'rebar'])
  const inputRef = useRef<HTMLInputElement>(null)

  const toggleCheck = (key: string) => {
    setEnabledChecks(prev =>
      prev.includes(key) ? prev.filter(c => c !== key) : [...prev, key]
    )
  }

  const visibleNodes = NODES.filter(n =>
    n.checkKey === null || enabledChecks.includes(n.checkKey)
  )

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
    form.append('checks', enabledChecks.join(','))

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
        setDoneNodes(visibleNodes.map((n) => n.key))
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

  const clearFile = () => {
    setFile(null); setResult(null); setDoneNodes([]); setActiveNode(null)
    setErrorMsg(''); setAppState('idle')
    if (inputRef.current) inputRef.current.value = ''
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

  const progress = Math.round(
    (doneNodes.filter(k => visibleNodes.some(n => n.key === k)).length / visibleNodes.length) * 100
  )
  const overall  = result
    ? result.summary.ERROR   > 0 ? 'FAIL'
    : result.summary.WARNING > 0 ? 'WARN' : 'PASS'
    : null

  // ── Render ─────────────────────────────────────────────────
  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">

      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-72' : 'w-16'} bg-[#0f172a] flex flex-col flex-shrink-0 transition-all duration-300 relative border-r border-slate-800/80 shadow-2xl`}>

        {/* Toggle */}
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="absolute -right-3.5 top-8 w-7 h-7 bg-slate-800 border border-slate-700 rounded-full flex items-center justify-center text-slate-400 hover:bg-blue-600 hover:text-white hover:border-blue-500 transition-all z-20 shadow-lg"
        >
          {sidebarOpen ? <ChevronLeft size={13} /> : <ChevronRight size={13} />}
        </button>

        {/* Brand */}
        <div className="border-b border-slate-800/80">
          <div className={`flex items-center gap-3.5 px-4 py-4 ${!sidebarOpen ? 'justify-center' : ''}`}>
            <img
              src="/logo.png"
              alt="Drawing Analyzer"
              className={`object-contain flex-shrink-0 rounded-xl ring-1 ring-blue-500/20 drop-shadow-[0_0_8px_rgba(59,130,246,0.3)] transition-all duration-300 ${sidebarOpen ? 'w-11 h-11' : 'w-9 h-9'}`}
            />
            {sidebarOpen && (
              <div className="overflow-hidden">
                <p className="text-[14px] font-black tracking-[0.1em] whitespace-nowrap leading-none">
                  <span className="text-white">DRAWING </span><span className="text-blue-400">ANALYZER</span>
                </p>
                <p className="text-[9px] text-slate-500 mt-1.5 tracking-[0.15em] uppercase font-semibold">AI-powered QA</p>
              </div>
            )}
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2.5 py-5 space-y-0.5">
          {NAV.map(({ icon: Icon, label, active }) => (
            <button key={label} title={!sidebarOpen ? label : undefined}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-[13px] font-medium transition-all duration-150 ${
                active
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/40'
                  : 'text-slate-500 hover:bg-slate-800/70 hover:text-slate-200'
              }`}
            >
              <Icon size={15} className="flex-shrink-0" />
              {sidebarOpen && <span className="truncate">{label}</span>}
            </button>
          ))}
        </nav>

        {/* Support */}
        <div className="px-2.5 pb-5 pt-3 border-t border-slate-800/80">
          <button title={!sidebarOpen ? 'Support' : undefined}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-[13px] font-medium text-slate-500 hover:bg-slate-800/70 hover:text-slate-200 transition-all">
            <HelpCircle size={15} className="flex-shrink-0" />
            {sidebarOpen && <span>Support</span>}
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Header */}
        <header className="bg-white border-b border-gray-200/70 px-8 py-3.5 flex items-center flex-shrink-0">
          <div>
            <h1 className="text-[15px] font-bold text-gray-900 tracking-tight">Dashboard</h1>
            <p className="text-[11px] text-gray-400 mt-0.5 tracking-wide">Structural drawing validation · PDF analysis</p>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-7 space-y-5">

          {/* Upload + Active checks */}
          <div className="grid grid-cols-2 gap-5">

            {/* Drop zone */}
            <div
              onClick={() => inputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={onDrop}
              className={`relative rounded-2xl p-10 text-center cursor-pointer transition-all duration-200 select-none border-2 border-dashed ${
                isDragging
                  ? 'border-blue-400 bg-blue-50/70 scale-[1.01]'
                  : 'border-gray-200 bg-white hover:border-blue-300 hover:bg-blue-50/20'
              }`}
            >
              <input ref={inputRef} type="file" accept=".pdf" className="hidden"
                onChange={e => e.target.files?.[0] && pickFile(e.target.files[0])} />

              <div className="w-16 h-16 mx-auto mb-5 rounded-2xl bg-gradient-to-br from-blue-50 to-slate-50 border border-blue-100/80 flex items-center justify-center shadow-sm">
                <FileText size={28} className="text-blue-400" />
              </div>
              <p className="font-bold text-gray-800 text-sm tracking-wide">Drag & drop building drawings here</p>
              <p className="text-xs text-gray-400 mt-1.5 tracking-wide">Supported: PDF · German Standards (DIN / EN)</p>
              <button onClick={e => { e.stopPropagation(); inputRef.current?.click() }}
                className="mt-6 px-6 py-2.5 bg-slate-900 text-white text-xs font-bold rounded-xl hover:bg-slate-700 transition-colors tracking-wide shadow-sm">
                Select Files from Computer
              </button>
            </div>

            {/* Active checks panel */}
            <div className="bg-white rounded-2xl border border-gray-200/70 p-5 flex flex-col gap-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.15em]">Active Checks</h2>
                {enabledChecks.length === 0 && (
                  <span className="text-[10px] text-red-400 font-semibold">Select at least one check</span>
                )}
              </div>

              {/* Check toggles */}
              <div className="flex gap-2 flex-wrap">
                {CHECK_OPTIONS.map(({ key, label }) => {
                  const on = enabledChecks.includes(key)
                  const disabled = appState === 'analyzing'
                  return (
                    <button
                      key={key}
                      onClick={() => !disabled && toggleCheck(key)}
                      disabled={disabled}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold border transition-all ${
                        disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
                      } ${
                        on
                          ? 'bg-blue-600 border-blue-600 text-white shadow-sm'
                          : 'bg-white border-gray-200 text-gray-400 hover:border-gray-300 hover:text-gray-600'
                      }`}
                    >
                      <span className={`w-3 h-3 rounded-sm border flex items-center justify-center flex-shrink-0 ${
                        on ? 'bg-white/30 border-white/50' : 'border-gray-300'
                      }`}>
                        {on && <span className="text-white text-[8px] leading-none font-black">✓</span>}
                      </span>
                      {label}
                    </button>
                  )
                })}
              </div>

              {!file ? (
                <div className="flex-1 flex flex-col items-center justify-center gap-2.5 py-6">
                  <div className="w-11 h-11 rounded-2xl bg-gray-50 border border-gray-100 flex items-center justify-center">
                    <FileText size={19} className="text-gray-300" />
                  </div>
                  <p className="text-sm text-gray-300 font-medium">No file selected</p>
                  <p className="text-[11px] text-gray-200 tracking-wide">Upload a PDF to begin</p>
                </div>
              ) : (
                <>
                  {/* File row */}
                  <div className="border border-gray-100 rounded-xl bg-gray-50/60">
                    <div className="flex items-center gap-3 px-3.5 py-3">
                      <div className="w-7 h-7 rounded-lg bg-blue-50 border border-blue-100 flex items-center justify-center flex-shrink-0">
                        <FileText size={13} className="text-blue-500" />
                      </div>
                      <span className="text-[13px] font-medium text-gray-700 truncate flex-1">{file.name}</span>

                      {appState === 'ready' && (
                        <>
                          <span className="text-[9px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full font-bold tracking-widest">READY</span>
                          <button
                            onClick={analyze}
                            disabled={enabledChecks.length === 0}
                            title={enabledChecks.length === 0 ? 'Select at least one check' : undefined}
                            className="ml-1 px-3 py-1.5 bg-blue-600 text-white text-[11px] font-bold rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors tracking-wide shadow-sm">
                            Start Check
                          </button>
                        </>
                      )}
                      {appState === 'analyzing' && (
                        <span className="text-[9px] bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full font-bold flex items-center gap-1 border border-blue-100 tracking-widest">
                          <Loader2 size={8} className="animate-spin" /> ANALYZING
                        </span>
                      )}
                      {appState === 'done' && (
                        <span className={`text-[9px] px-2 py-0.5 rounded-full font-bold tracking-widest ${
                          overall === 'FAIL' ? 'bg-red-50 text-red-600 border border-red-100' : 'bg-green-50 text-green-600 border border-green-100'
                        }`}>
                          DONE · {result?.summary.ERROR ?? 0} ERR
                        </span>
                      )}
                      {appState === 'error' && (
                        <span className="text-[9px] bg-red-50 text-red-500 px-2 py-0.5 rounded-full font-bold border border-red-100 tracking-widest">FAILED</span>
                      )}
                      {appState !== 'analyzing' && (
                        <button onClick={clearFile}
                          className="w-5 h-5 flex items-center justify-center rounded-full text-gray-300 hover:bg-red-50 hover:text-red-400 transition-colors text-base font-bold flex-shrink-0"
                          title="Remove file">×</button>
                      )}
                    </div>
                  </div>

                  {/* Progress */}
                  {appState === 'analyzing' && (
                    <div className="space-y-3">
                      <div>
                        <div className="flex justify-between text-[11px] mb-1.5">
                          <span className="text-gray-400 font-medium">Analyzing drawing…</span>
                          <span className="text-blue-500 font-bold">{progress}%</span>
                        </div>
                        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-blue-600 to-blue-400 rounded-full transition-all duration-500"
                            style={{ width: `${progress}%` }}
                          />
                        </div>
                      </div>
                      <div className="space-y-2">
                        {visibleNodes.map(node => {
                          const done    = doneNodes.includes(node.key)
                          const running = activeNode === node.key && !done
                          return (
                            <div key={node.key} className="flex items-center gap-2.5">
                              {done ? (
                                <CheckCircle size={13} className="text-green-500 flex-shrink-0" />
                              ) : running ? (
                                <Loader2 size={13} className="text-blue-500 animate-spin flex-shrink-0" />
                              ) : (
                                <div className="w-[13px] h-[13px] rounded-full border border-gray-200 flex-shrink-0" />
                              )}
                              <span className={`text-[12px] ${done ? 'text-gray-500' : running ? 'text-blue-600 font-semibold' : 'text-gray-300'}`}>
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
                    <div className="space-y-2">
                      <div className="text-xs text-red-600 bg-red-50 rounded-xl p-3.5 border border-red-100 leading-relaxed">
                        {errorMsg}
                      </div>
                      <button onClick={analyze}
                        className="w-full py-2.5 bg-blue-600 text-white text-xs font-bold rounded-xl hover:bg-blue-700 transition-colors tracking-wide shadow-sm">
                        Re-Analyze
                      </button>
                    </div>
                  )}

                  {/* Done summary */}
                  {appState === 'done' && result && (
                    <div className="flex gap-4 text-xs px-0.5">
                      <span className="text-red-500 font-semibold">{result.summary.ERROR} errors</span>
                      <span className="text-amber-500 font-semibold">{result.summary.WARNING} warnings</span>
                      <span className="text-green-500 font-semibold">{result.summary.INFO} OK</span>
                      <span className="ml-auto text-gray-400">{result.pdf_pages} page(s)</span>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Results table */}
          {result && (
            <div className="bg-white rounded-2xl border border-gray-200/70 overflow-hidden shadow-sm">

              <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
                <div>
                  <h2 className="font-bold text-gray-900 text-sm tracking-tight">
                    Analysis Results
                    <span className="ml-2 text-xs font-normal text-gray-400">· {result.pdf_pages} page(s)</span>
                  </h2>
                  <p className="text-[11px] text-gray-400 mt-0.5 tracking-wide">
                    {result.sections.map(s => `${s.title}: ${s.count}`).join(' · ')}
                  </p>
                </div>
                <button onClick={downloadReport}
                  className="flex items-center gap-2 px-4 py-2 bg-slate-900 text-white text-xs font-bold rounded-xl hover:bg-slate-700 transition-colors tracking-wide shadow-sm">
                  <Download size={13} />Download Report
                </button>
              </div>

              {/* Summary strip */}
              <div className="px-6 py-3 bg-gray-50/60 border-b border-gray-100 flex items-center gap-6 flex-wrap">
                <span className="flex items-center gap-1.5 text-xs text-gray-600">
                  <CheckCircle size={13} className="text-green-500" /><strong>{result.summary.INFO}</strong> OK
                </span>
                <span className="flex items-center gap-1.5 text-xs text-gray-600">
                  <AlertTriangle size={13} className="text-amber-500" /><strong>{result.summary.WARNING}</strong> Warnings
                </span>
                <span className="flex items-center gap-1.5 text-xs text-gray-600">
                  <AlertCircle size={13} className="text-red-500" /><strong>{result.summary.ERROR}</strong> Errors
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <span className="text-[10px] text-gray-400 font-semibold uppercase tracking-widest">Overall</span>
                  <span className={`px-3 py-1 rounded-full text-[11px] font-bold tracking-wide ${
                    overall === 'FAIL' ? 'bg-red-100 text-red-700' :
                    overall === 'WARN' ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'
                  }`}>{overall}</span>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-gray-50/80 border-b border-gray-100 text-[10px] font-bold text-gray-400 uppercase tracking-widest">
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
                    {result.sections.flatMap(s => s.issues).map((issue: Issue) => {
                      const { cls, label } = severityBadge(issue.severity)
                      return (
                        <tr key={issue.id} className="hover:bg-blue-50/20 transition-colors">
                          <td className="px-5 py-3.5 text-gray-300 font-mono text-[11px]">{issue.id}</td>
                          <td className="px-5 py-3.5">
                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide ${catBadge(issue.category)}`}>
                              {issue.category}
                            </span>
                          </td>
                          <td className="px-5 py-3.5 text-gray-500 text-xs">{issue.page}</td>
                          <td className="px-5 py-3.5 text-gray-500 max-w-[140px] truncate text-xs" title={issue.location}>
                            {issue.location}
                          </td>
                          <td className="px-5 py-3.5 text-gray-500 text-xs">{Math.round(issue.confidence * 100)}%</td>
                          <td className="px-5 py-3.5">
                            <span className={`px-2.5 py-0.5 rounded text-[10px] font-bold tracking-wide ${cls}`}>{label}</span>
                          </td>
                          <td className="px-5 py-3.5 text-gray-700 max-w-sm text-xs leading-relaxed">{issue.description}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              <div className="px-6 py-3 border-t border-gray-100 bg-gray-50/40 flex items-center gap-5 text-[11px] text-gray-400">
                <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-green-500" />PASS</span>
                <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500" />FAIL</span>
                <span className="ml-1">
                  {result.summary.total} issues · <strong className="text-gray-600">{result.summary.total - result.summary.ERROR}</strong> passed · <strong className="text-red-500">{result.summary.ERROR}</strong> failed
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
