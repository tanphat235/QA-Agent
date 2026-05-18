import { useState, useRef, useCallback, useEffect } from 'react'
import {
  LayoutDashboard, History, HelpCircle,
  FileText, CheckCircle, AlertTriangle,
  Download, Loader2, ChevronLeft, ChevronRight, ChevronDown,
  XCircle, BookOpen, Save, Pencil,
} from 'lucide-react'

// ── Types ────────────────────────────────────────────────────
interface Issue {
  id: string
  category: string
  severity: string      // "ERROR" | "WARNING" | "INFO"
  description: string
  page: number
  location: string
  confidence: number
  passed?: boolean      // set only on check-summary items
  check_name?: string   // set only on check-summary items
  not_found?: boolean   // set only when required drawing info was absent
}
interface Section {
  category: string
  title: string
  count: number
  issue_count: number
  checks_passed?: number
  checks_failed?: number
  checks_not_found?: number
  issues: Issue[]
}
interface AnalysisResult {
  status: string
  message: string
  pdf_pages: number
  summary: { total: number; ERROR: number; WARNING: number; INFO: number }
  sections: Section[]
}
interface HistoryEntry {
  id: string
  filename: string
  timestamp: number
  checks: string[]
  result: AnalysisResult
}
interface TrainingMistake {
  id: string
  check_key: string
  title: string
  wrong: string
  correct: string
}
type TrainingData = Record<string, TrainingMistake[]>

type AppState    = 'idle' | 'ready' | 'analyzing' | 'done' | 'error'
type ResultFilter = null | 'passed' | 'failed' | 'issues'
type ActiveView  = 'dashboard' | 'history' | 'training'

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
  { key: 'spell', label: 'Spelling & Title Block', color: 'gray' },
  { key: 'bend',  label: 'Bending & Schedule',    color: 'purple' },
  { key: 'rebar', label: 'Rebar Labels & Dims',   color: 'blue' },
] as const
const NAV = [
  { icon: LayoutDashboard, label: 'Dashboard',    view: 'dashboard' as ActiveView },
  { icon: History,         label: 'Check History', view: 'history'  as ActiveView },
  { icon: BookOpen,        label: 'AI Training',   view: 'training' as ActiveView },
]

const NODE_SECTIONS = [
  {
    key: 'bend',
    title: 'Bending & Schedule',
    checks: [
      { key: 'pos_count',       title: 'Last Position Number vs Title Block' },
      { key: 'pos_coverage',    title: 'Pos Coverage' },
      { key: 'mesh_pos',        title: 'Mesh Reinforcement Pos' },
      { key: 'mesh_ratio',      title: 'Mesh-to-Total Mass Ratio' },
      { key: 'mass_arithmetic', title: 'Total Mass Arithmetic' },
      { key: 'bending_angle',   title: 'Bending Angle / Mandrel Diameter' },
      { key: 'bar_length',      title: 'Bar Length vs Schedule' },
    ],
  },
  {
    key: 'spell',
    title: 'Spelling & Title Block',
    checks: [
      { key: 'spelling',         title: 'Spelling' },
      { key: 'section_name',     title: 'Section Name Completeness' },
      { key: 'component_name',   title: 'Component Name vs Title Block' },
      { key: 'section_scale',    title: 'Scale Consistency' },
      { key: 'grid_lines',       title: 'Grid Lines Consistency' },
      { key: 'parts_lists',      title: 'Parts Lists Present' },
      { key: 'parts_quantities', title: 'Parts Quantities' },
      { key: 'parts_labels',     title: 'Built-in Part Labels' },
      { key: '3d_view',          title: '3D View' },
      { key: 'drawing_title',    title: 'Drawing Title vs Title Block' },
    ],
  },
  {
    key: 'rebar',
    title: 'Rebar Labels & Dims',
    checks: [
      { key: 'spacer_label',         title: 'Spacer/Clamp Label Suffix' },
      { key: 'pin_width_vertical',   title: 'Vertical Pin Width' },
      { key: 'pin_width_horizontal', title: 'Horizontal Pin Width' },
      { key: 'spacer_width',         title: 'Spacer/Clamp Width' },
    ],
  },
]

// ── Tree-building types ──────────────────────────────────────
interface CheckSubItem {
  summary: Issue    // per-Schnitt or per-Pos summary
  issues: Issue[]   // individual issue items directly following this sub-summary
}
interface CheckGroup {
  key: string         // prefix before " – " (or full name if no sub-items)
  displayName: string // resolved from overall summary if available
  overall?: Issue     // the overall summary item
  subItems: CheckSubItem[]
  orphanIssues: Issue[]
}

function buildCheckGroups(sectionIssues: Issue[]): CheckGroup[] {
  const groups: CheckGroup[] = []
  const groupMap = new Map<string, CheckGroup>()
  let currentGroup: CheckGroup | null = null
  let currentSubItem: CheckSubItem | null = null

  for (const issue of sectionIssues) {
    if (!issue.check_name) {
      // Orphan issue — attach to the most recent sub-item or group
      if (currentSubItem) {
        currentSubItem.issues.push(issue)
      } else if (currentGroup) {
        currentGroup.orphanIssues.push(issue)
      }
      continue
    }

    const dashIdx = issue.check_name.indexOf(' – ')  // ' – '
    const groupKey = dashIdx >= 0 ? issue.check_name.substring(0, dashIdx) : issue.check_name

    if (!groupMap.has(groupKey)) {
      const g: CheckGroup = { key: groupKey, displayName: groupKey, subItems: [], orphanIssues: [] }
      groupMap.set(groupKey, g)
      groups.push(g)
    }

    currentGroup = groupMap.get(groupKey)!

    if (dashIdx >= 0) {
      // Sub-summary (per Pos / per Schnitt)
      const sub: CheckSubItem = { summary: issue, issues: [] }
      currentGroup.subItems.push(sub)
      currentSubItem = sub
    } else {
      // Overall summary for this check
      currentGroup.overall = issue
      currentGroup.displayName = issue.check_name
      currentSubItem = null   // overall resets the current sub-item context
    }
  }

  return groups
}

// ── Helpers ──────────────────────────────────────────────────
function severityBadge(s: string) {
  if (s === 'ERROR' || s === 'WARNING')
    return { cls: 'bg-red-100 text-red-700 border border-red-200', label: 'FAIL' }
  return { cls: 'bg-green-100 text-green-700 border border-green-200', label: 'OK' }
}

// ── History storage ───────────────────────────────────────────
const HISTORY_KEY = 'qa_history'
const HISTORY_MAX = 10

function loadHistory(): HistoryEntry[] {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? '[]') } catch { return [] }
}
function saveHistory(entries: HistoryEntry[]): void {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_MAX)))
}
function fmtDate(ts: number): string {
  const d    = new Date(ts)
  const now  = new Date()
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === now.toDateString()) return `Today · ${time}`
  if (d.toDateString() === new Date(now.getTime() - 86400000).toDateString()) return `Yesterday · ${time}`
  return `${d.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })} · ${time}`
}
function historyStats(entry: HistoryEntry) {
  const all      = entry.result.sections.flatMap(s => s.issues)
  const passed   = all.filter(i => i.passed === true).length
  const failed   = all.filter(i => i.passed === false).length
  const notFound = all.filter(i => i.not_found === true).length
  return { passed, failed, issues: notFound }
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
  spell: 'Spelling & Title Block',
  bend:  'Bending & Schedule',
  rebar: 'Rebar Labels & Dims',
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
        ...(typeof it.passed === 'boolean'    ? { passed: it.passed }         : {}),
        ...(typeof it.check_name === 'string' ? { check_name: it.check_name } : {}),
        ...(it.not_found === true             ? { not_found: true }           : {}),
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
        ...(typeof it.passed === 'boolean'    ? { passed: it.passed }         : {}),
        ...(typeof it.check_name === 'string' ? { check_name: it.check_name } : {}),
        ...(it.not_found === true             ? { not_found: true }           : {}),
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
    .map(cat => {
      const catIssues = byCategory[cat]
      const checkSums = catIssues.filter(i => i.passed !== undefined || i.not_found === true)
      return {
        category: cat,
        title: _CAT_TITLES[cat] ?? cat,
        count: catIssues.length,
        issue_count: catIssues.filter(i => i.passed === undefined && !i.not_found).length,
        checks_passed:     checkSums.filter(i => i.passed === true).length,
        checks_failed:     checkSums.filter(i => i.passed === false).length,
        checks_not_found:  checkSums.filter(i => i.not_found === true).length,
        issues: catIssues,
      }
    })

  const allFlat   = issues.filter(i => i.passed === undefined)
  const total   = allFlat.length
  const ERROR   = allFlat.filter(i => i.severity === 'ERROR').length
  const WARNING = allFlat.filter(i => i.severity === 'WARNING').length
  const INFO    = allFlat.filter(i => i.severity === 'INFO').length

  return {
    status: 'completed',
    message: total === 0 ? 'No issues found.' : `${total} issue(s): ${ERROR} error, ${WARNING} warning.`,
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
  const [sidebarOpen, setSidebarOpen]       = useState(true)
  const [enabledChecks, setEnabledChecks]   = useState<string[]>(['spell', 'bend', 'rebar'])
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set())
  const [expandedGroups,    setExpandedGroups]    = useState<Set<string>>(new Set())
  const [resultFilter,      setResultFilter]      = useState<ResultFilter>(null)
  const [activeView,        setActiveView]        = useState<ActiveView>('dashboard')
  const [historyEntries,    setHistoryEntries]    = useState<HistoryEntry[]>(() => loadHistory())
  const [viewingEntry,           setViewingEntry]           = useState<HistoryEntry | null>(null)
  const [trainingData,           setTrainingData]           = useState<TrainingData>({})
  const [trainingLoading,        setTrainingLoading]        = useState(false)
  const [trainingSaving,         setTrainingSaving]         = useState(false)
  const [trainingSaveOk,         setTrainingSaveOk]         = useState(false)
  const [activeTrainingTab,      setActiveTrainingTab]      = useState('bend')
  const [expandedTrainingChecks, setExpandedTrainingChecks] = useState<Set<string>>(new Set())
  const [editingMistakes,        setEditingMistakes]        = useState<Set<string>>(new Set())
  const [cardErrors,             setCardErrors]             = useState<Record<string, string>>({})
  const inputRef = useRef<HTMLInputElement>(null)

  const toggleSection = (cat: string) =>
    setCollapsedSections(prev => {
      const next = new Set(prev); next.has(cat) ? next.delete(cat) : next.add(cat); return next
    })
  const toggleGroup = (key: string) =>
    setExpandedGroups(prev => {
      const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next
    })
  const toggleFilter = (f: ResultFilter) =>
    setResultFilter(prev => prev === f ? null : f)

  // Auto-expand failed/issue groups when result arrives; reset on clear
  useEffect(() => {
    if (!result) { setExpandedGroups(new Set()); setResultFilter(null); return }
    const expandKeys = new Set<string>()
    for (const section of result.sections) {
      for (const group of buildCheckGroups(section.issues)) {
        const failed = group.overall
          ? group.overall.passed === false
          : group.subItems.some(s => s.summary.passed === false && !s.summary.not_found)
        const notFound = group.overall?.not_found === true
        const hasIssues =
          group.orphanIssues.length > 0 ||
          group.subItems.some(s => s.issues.length > 0)
        if (failed || notFound || hasIssues) expandKeys.add(`${section.category}::${group.key}`)
      }
    }
    setExpandedGroups(expandKeys)
  }, [result])

  // Save completed analysis to localStorage history
  useEffect(() => {
    if (appState !== 'done' || !result || !file) return
    const entry: HistoryEntry = {
      id: `${Date.now()}_${file.name}`,
      filename: file.name,
      timestamp: Date.now(),
      checks: [...enabledChecks],
      result,
    }
    setHistoryEntries(prev => {
      const next = [entry, ...prev.filter(e => e.filename !== file.name || Math.abs(e.timestamp - entry.timestamp) > 5000)].slice(0, HISTORY_MAX)
      saveHistory(next)
      return next
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appState])

  const clearHistory = () => {
    localStorage.removeItem(HISTORY_KEY)
    setHistoryEntries([])
  }

  // Load structured training data when training view is opened
  useEffect(() => {
    if (activeView !== 'training') return
    setTrainingLoading(true)
    fetch('/api/mistakes-structured')
      .then(r => r.json())
      .then((d: TrainingData) => {
        setTrainingData(d)
        setExpandedTrainingChecks(new Set())  // all collapsed by default
        setEditingMistakes(new Set())          // all read-only — already saved
      })
      .catch(() => {})
      .finally(() => setTrainingLoading(false))
  }, [activeView])

  const saveMistakes = async () => {
    setTrainingSaving(true)
    setTrainingSaveOk(false)
    try {
      const res = await fetch('/api/mistakes-structured', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: trainingData }),
      })
      if (res.ok) {
        setTrainingSaveOk(true)
        setTimeout(() => {
          setTrainingSaveOk(false)
          setEditingMistakes(new Set())  // exit edit mode after brief confirmation
        }, 800)
      }
    } finally {
      setTrainingSaving(false)
    }
  }

  const updateMistake = (section: string, updated: TrainingMistake) => {
    setCardErrors(prev => { const next = { ...prev }; delete next[updated.id]; return next })
    setTrainingData(prev => ({
      ...prev,
      [section]: (prev[section] ?? []).map(m => m.id === updated.id ? updated : m),
    }))
  }

  const deleteMistake = (section: string, id: string) => {
    setTrainingData(prev => {
      const next = { ...prev, [section]: (prev[section] ?? []).filter(m => m.id !== id) }
      fetch('/api/mistakes-structured', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: next }),
      })
      return next
    })
  }

  const addMistake = (section: string, check_key: string) => {
    const newItem: TrainingMistake = {
      id: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
      check_key,
      title: '',
      wrong: '',
      correct: '',
    }
    setTrainingData(prev => ({ ...prev, [section]: [...(prev[section] ?? []), newItem] }))
    setExpandedTrainingChecks(prev => new Set([...prev, `${section}::${check_key}`]))
    setEditingMistakes(prev => new Set([...prev, newItem.id]))  // new mistake starts in edit mode
  }

  const toggleTrainingCheck = (key: string) =>
    setExpandedTrainingChecks(prev => {
      const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next
    })

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
    setViewingEntry(null); setAppState('ready')
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setIsDragging(false)
    const f = e.dataTransfer.files[0]; if (f) pickFile(f)
  }, [])

  const analyze = async () => {
    if (!file) return
    setAppState('analyzing'); setDoneNodes([]); setActiveNode(null); setResult(null); setViewingEntry(null)

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
            thread_id?: string
            studio_url?: string
          }

          if (payload.type === 'ack') {
            /* backend received file; optional UX hook */
          } else if (payload.type === 'run_started') {
            /* thread created on LangGraph API — visible in LangSmith Studio */
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
    setViewingEntry(null); setErrorMsg(''); setAppState('idle')
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

  // Stats — count at sub-item level: each Schnitt/Pos counts as 1;
  // groups with no sub-items (just an overall) count as 1.
  const _countChecks = (wantPassed: boolean) =>
    (result?.sections ?? []).reduce((total, section) =>
      total + buildCheckGroups(section.issues).reduce((n, group) => {
        if (group.subItems.length > 0)
          return n + group.subItems.filter(sub => sub.summary.passed === wantPassed).length
        return n + (group.overall?.passed === wantPassed ? 1 : 0)
      }, 0)
    , 0)
  const totalChecksPassed = _countChecks(true)
  const totalChecksFailed = _countChecks(false)
  const totalNotFound = (result?.sections ?? []).reduce((total, section) =>
    total + buildCheckGroups(section.issues).reduce((n, group) => {
      if (group.subItems.length > 0)
        return n + group.subItems.filter(sub => sub.summary.not_found === true).length
      return n + (group.overall?.not_found === true ? 1 : 0)
    }, 0)
  , 0)

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
          {NAV.map(({ icon: Icon, label, view }) => {
            const isActive = activeView === view
            const badge = view === 'history' && historyEntries.length > 0 ? historyEntries.length : null
            return (
              <button key={label} title={!sidebarOpen ? label : undefined}
                onClick={() => setActiveView(view)}
                className={`relative w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-[13px] font-medium transition-all duration-150 ${
                  isActive
                    ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/40'
                    : 'text-slate-500 hover:bg-slate-800/70 hover:text-slate-200'
                }`}
              >
                <Icon size={15} className="flex-shrink-0" />
                {sidebarOpen && <span className="flex-1 text-center truncate">{label}</span>}
                {sidebarOpen && badge !== null && (
                  <span className={`absolute right-3 text-[10px] font-bold px-1.5 py-0.5 rounded-full ${isActive ? 'bg-white/20 text-white' : 'bg-slate-700 text-slate-300'}`}>
                    {badge}
                  </span>
                )}
              </button>
            )
          })}
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
            <h1 className="text-[15px] font-bold text-gray-900 tracking-tight">
              {activeView === 'history' ? 'Check History' : activeView === 'training' ? 'AI Training' : 'Dashboard'}
            </h1>
            <p className="text-[11px] text-gray-400 mt-0.5 tracking-wide">
              {activeView === 'history'
                ? `${historyEntries.length} of ${HISTORY_MAX} recent analyses stored`
                : activeView === 'training'
                  ? 'Edit common AI mistakes · Saved file is injected into every analysis'
                  : 'Structural drawing validation · PDF analysis'}
            </p>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-7 space-y-5">

          {/* ── History view ─────────────────────────────── */}
          {activeView === 'history' && (
            <div className="space-y-3">

              {historyEntries.length === 0 ? (
                <div className="bg-white rounded-2xl border border-gray-200/70 flex flex-col items-center justify-center py-16 gap-3 shadow-sm">
                  <History size={32} className="text-gray-200" />
                  <p className="text-sm font-medium text-gray-400">No analyses yet</p>
                  <p className="text-xs text-gray-300">Complete an analysis to see it here</p>
                  <button onClick={() => setActiveView('dashboard')}
                    className="mt-2 px-5 py-2 bg-blue-600 text-white text-xs font-bold rounded-xl hover:bg-blue-700 transition-colors">
                    Go to Dashboard
                  </button>
                </div>
              ) : (
                <>
                  <div className="flex justify-end">
                    <button onClick={clearHistory}
                      className="text-[11px] text-gray-400 hover:text-red-500 transition-colors font-medium flex items-center gap-1">
                      <XCircle size={12} /> Clear all history
                    </button>
                  </div>

                  {historyEntries.map(entry => {
                    const { passed, failed, issues } = historyStats(entry)
                    const checkLabels = entry.checks.map(c =>
                      CHECK_OPTIONS.find(o => o.key === c)?.label ?? c
                    )
                    return (
                      <div key={entry.id}
                        className="bg-white rounded-2xl border border-gray-200/70 px-6 py-4 shadow-sm hover:border-blue-200 hover:shadow-md transition-all">
                        <div className="flex items-start gap-4">
                          <div className="w-9 h-9 rounded-xl bg-blue-50 border border-blue-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                            <FileText size={15} className="text-blue-500" />
                          </div>

                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm font-bold text-gray-800 truncate">{entry.filename}</span>
                              <span className="text-[10px] text-gray-400 flex-shrink-0">{fmtDate(entry.timestamp)}</span>
                            </div>

                            <div className="flex gap-1.5 flex-wrap mt-1.5">
                              {checkLabels.map(lbl => (
                                <span key={lbl} className="text-[10px] px-2 py-0.5 bg-slate-100 text-slate-500 rounded-full font-medium">{lbl}</span>
                              ))}
                            </div>

                            <div className="flex items-center gap-4 mt-2.5 text-xs">
                              <span className="flex items-center gap-1 text-green-600">
                                <CheckCircle size={11} /> <strong>{passed}</strong> passed
                              </span>
                              <span className={`flex items-center gap-1 ${failed > 0 ? 'text-red-600' : 'text-gray-400'}`}>
                                <XCircle size={11} /> <strong>{failed}</strong> failed
                              </span>
                              {issues > 0 && (
                                <span className="flex items-center gap-1 text-amber-600">
                                  <AlertTriangle size={11} /> <strong>{issues}</strong> not found
                                </span>
                              )}
                              <span className="text-gray-300 text-[10px]">{entry.result.pdf_pages} page(s)</span>
                            </div>
                          </div>

                          <button
                            onClick={() => {
                              setResult(entry.result)
                              setViewingEntry(entry)
                              setFile(null)
                              setAppState('done')
                              setActiveView('dashboard')
                            }}
                            className="flex-shrink-0 flex items-center gap-1.5 px-4 py-2 bg-slate-900 text-white text-xs font-bold rounded-xl hover:bg-blue-600 transition-colors self-center">
                            View <ChevronRight size={12} />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </>
              )}
            </div>
          )}

          {/* ── Training view ───────────────────────────── */}
          {activeView === 'training' && (
            <div className="space-y-4">

              {/* Header */}
              <div className="bg-white rounded-2xl border border-gray-200/70 px-6 py-4 shadow-sm flex items-center gap-4">
                <div className="w-9 h-9 rounded-xl bg-blue-50 border border-blue-100 flex items-center justify-center flex-shrink-0">
                  <BookOpen size={16} className="text-blue-500" />
                </div>
                <div className="min-w-0">
                  <p className="text-[13px] font-bold text-gray-800">Known AI Check Mistakes</p>
                  <p className="text-[11px] text-gray-400 mt-0.5">
                    Each entry records a confirmed AI check error and is injected into every analysis prompt to prevent the same mistake from recurring.
                  </p>
                </div>
              </div>

              {trainingLoading ? (
                <div className="flex items-center justify-center py-20 gap-2 text-gray-400">
                  <Loader2 size={18} className="animate-spin" />
                  <span className="text-sm">Loading…</span>
                </div>
              ) : <>

              {/* Section tabs */}
              <div className="flex gap-2 flex-wrap">
                {NODE_SECTIONS.map(sec => {
                  const isActive = activeTrainingTab === sec.key
                  return (
                    <button key={sec.key} onClick={() => setActiveTrainingTab(sec.key)}
                      className={`px-4 py-2 rounded-xl text-[12px] font-bold transition-all ${
                        isActive
                          ? 'bg-slate-900 text-white shadow-sm'
                          : 'bg-white border border-gray-200 text-gray-500 hover:border-gray-300 hover:text-gray-700'
                      }`}
                    >
                      {sec.title}
                    </button>
                  )
                })}
              </div>

              {/* Check groups for active tab */}
              {(NODE_SECTIONS.find(s => s.key === activeTrainingTab)?.checks ?? []).map(check => {
                const gKey    = `${activeTrainingTab}::${check.key}`
                const expanded = expandedTrainingChecks.has(gKey)
                const mistakes = (trainingData[activeTrainingTab] ?? []).filter(m => m.check_key === check.key)

                return (
                  <div key={check.key} className="bg-white rounded-2xl border border-gray-200/70 overflow-hidden shadow-sm">

                    {/* Check header */}
                    <button
                      onClick={() => toggleTrainingCheck(gKey)}
                      className="w-full px-5 py-3 flex items-center gap-3 hover:bg-gray-50/60 transition-colors"
                    >
                      <ChevronDown size={13} className={`text-gray-400 transition-transform flex-shrink-0 ${expanded ? 'rotate-180' : ''}`} />
                      <span className="text-[13px] font-semibold text-gray-700 flex-1 text-left">{check.title}</span>
                      {mistakes.length > 0 && (
                        <span className="text-[10px] px-2 py-0.5 bg-amber-100 text-amber-700 border border-amber-200 rounded-full font-bold flex-shrink-0">
                          {mistakes.length} mistake{mistakes.length > 1 ? 's' : ''}
                        </span>
                      )}
                    </button>

                    {expanded && (
                      <div className="border-t border-gray-100 px-5 py-4 space-y-3">

                        {mistakes.length === 0 && (
                          <p className="text-[12px] text-gray-300 italic">No mistakes recorded for this check.</p>
                        )}

                        {mistakes.map((mistake, idx) => {
                          const isEditing = editingMistakes.has(mistake.id)
                          return (
                            <div key={mistake.id} className={`border rounded-xl overflow-hidden transition-colors ${isEditing ? 'border-blue-200 bg-blue-50/10' : 'border-gray-200 bg-gray-50/40'}`}>
                              {/* Title row */}
                              <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-gray-100">
                                <span className="text-[10px] font-bold text-gray-300 flex-shrink-0 w-4">#{idx + 1}</span>
                                {isEditing ? (
                                  <input
                                    value={mistake.title}
                                    onChange={e => updateMistake(activeTrainingTab, { ...mistake, title: e.target.value })}
                                    placeholder="Brief description of this mistake…"
                                    className="flex-1 text-[12px] font-semibold text-gray-700 bg-transparent focus:outline-none placeholder:text-gray-300"
                                    autoFocus
                                  />
                                ) : (
                                  <span className="flex-1 text-[12px] font-semibold text-gray-400 truncate">
                                    {mistake.title || <span className="italic text-gray-300 font-normal">No title</span>}
                                  </span>
                                )}
                                {isEditing ? (
                                  <button
                                    onClick={() => {
                                      const m = (trainingData[activeTrainingTab] ?? []).find(x => x.id === mistake.id)
                                      if (!m) return
                                      const missing: string[] = []
                                      if (!m.title.trim())   missing.push('Title')
                                      if (!m.wrong.trim())   missing.push('Wrong')
                                      if (!m.correct.trim()) missing.push('Correct')
                                      if (missing.length) {
                                        setCardErrors(prev => ({ ...prev, [mistake.id]: `Required: ${missing.join(', ')}` }))
                                        return
                                      }
                                      setCardErrors(prev => { const next = { ...prev }; delete next[mistake.id]; return next })
                                      saveMistakes()
                                    }}
                                    disabled={trainingSaving}
                                    className={`flex items-center gap-1 text-[10px] font-bold px-2.5 py-1 rounded-lg transition-all flex-shrink-0 ${
                                      trainingSaveOk
                                        ? 'bg-green-500 text-white'
                                        : 'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50'
                                    }`}
                                  >
                                    {trainingSaving
                                      ? <Loader2 size={10} className="animate-spin" />
                                      : <Save size={10} />}
                                    {trainingSaveOk ? 'Saved!' : trainingSaving ? '…' : 'Save'}
                                  </button>
                                ) : (
                                  <button
                                    onClick={() => setEditingMistakes(prev => new Set([...prev, mistake.id]))}
                                    className="text-gray-300 hover:text-blue-500 transition-colors flex-shrink-0"
                                    title="Edit"
                                  ><Pencil size={13} /></button>
                                )}
                                <button
                                  onClick={() => deleteMistake(activeTrainingTab, mistake.id)}
                                  className="text-gray-300 hover:text-red-500 transition-colors flex-shrink-0"
                                  title="Delete"
                                ><XCircle size={14} /></button>
                              </div>
                              {/* Validation error */}
                              {isEditing && cardErrors[mistake.id] && (
                                <div className="px-3.5 py-2 bg-red-50 border-b border-red-100 flex items-center gap-1.5">
                                  <XCircle size={11} className="text-red-400 flex-shrink-0" />
                                  <span className="text-[11px] text-red-600 font-medium">{cardErrors[mistake.id]}</span>
                                </div>
                              )}
                              {/* WRONG */}
                              <div className="px-3.5 py-2.5 border-b border-gray-100">
                                <p className={`text-[10px] font-black uppercase tracking-wider mb-1 ${isEditing ? 'text-red-500' : 'text-red-300'}`}>Wrong</p>
                                {isEditing ? (
                                  <textarea
                                    value={mistake.wrong}
                                    onChange={e => updateMistake(activeTrainingTab, { ...mistake, wrong: e.target.value })}
                                    placeholder="What the AI did incorrectly…"
                                    rows={2}
                                    className="w-full text-[11px] text-gray-600 bg-white border border-gray-200 rounded-lg px-2.5 py-2 resize-y focus:outline-none focus:ring-1 focus:ring-red-300 focus:border-red-300 leading-relaxed"
                                  />
                                ) : (
                                  <p className={`text-[11px] leading-relaxed ${mistake.wrong ? 'text-gray-400' : 'italic text-gray-300'}`}>
                                    {mistake.wrong || 'Not set'}
                                  </p>
                                )}
                              </div>
                              {/* CORRECT */}
                              <div className="px-3.5 py-2.5">
                                <p className={`text-[10px] font-black uppercase tracking-wider mb-1 ${isEditing ? 'text-green-600' : 'text-green-300'}`}>Correct</p>
                                {isEditing ? (
                                  <textarea
                                    value={mistake.correct}
                                    onChange={e => updateMistake(activeTrainingTab, { ...mistake, correct: e.target.value })}
                                    placeholder="The correct behavior or rule…"
                                    rows={2}
                                    className="w-full text-[11px] text-gray-600 bg-white border border-gray-200 rounded-lg px-2.5 py-2 resize-y focus:outline-none focus:ring-1 focus:ring-green-300 focus:border-green-300 leading-relaxed"
                                  />
                                ) : (
                                  <p className={`text-[11px] leading-relaxed ${mistake.correct ? 'text-gray-400' : 'italic text-gray-300'}`}>
                                    {mistake.correct || 'Not set'}
                                  </p>
                                )}
                              </div>
                            </div>
                          )
                        })}

                        <button
                          onClick={() => addMistake(activeTrainingTab, check.key)}
                          className="flex items-center gap-1.5 text-[11px] font-semibold text-blue-500 hover:text-blue-700 transition-colors py-0.5"
                        >
                          <span className="w-4 h-4 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-black text-[10px]">+</span>
                          Add Mistake
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}

              </>}
            </div>
          )}

          {/* ── Dashboard view ───────────────────────────── */}
          {activeView === 'dashboard' && <>

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
              <p className="font-bold text-gray-800 text-sm tracking-wide">Drop your rebar detailing drawing here</p>
              <p className="text-xs text-gray-400 mt-1.5 tracking-wide">Single PDF · Structural Rebar Detailing · DIN / EN</p>
              <button onClick={e => { e.stopPropagation(); inputRef.current?.click() }}
                className="mt-6 px-6 py-2.5 bg-slate-900 text-white text-xs font-bold rounded-xl hover:bg-slate-700 transition-colors tracking-wide shadow-sm">
                Upload PDF File
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

              {!file && viewingEntry ? (
                /* Viewing a history entry — show its file info */
                <div className="space-y-3">
                  <div className="border border-blue-100 rounded-xl bg-blue-50/40 px-4 py-3 flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-blue-100 border border-blue-200 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <History size={13} className="text-blue-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-[12px] font-bold text-blue-800 truncate">{viewingEntry.filename}</p>
                      <p className="text-[10px] text-blue-500 mt-0.5">{fmtDate(viewingEntry.timestamp)}</p>
                      <div className="flex gap-1 flex-wrap mt-1.5">
                        {viewingEntry.checks.map(c => (
                          <span key={c} className="text-[9px] px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded-full font-semibold">
                            {CHECK_OPTIONS.find(o => o.key === c)?.label ?? c}
                          </span>
                        ))}
                      </div>
                    </div>
                    <button onClick={clearFile} title="Close history view"
                      className="text-blue-300 hover:text-blue-600 transition-colors flex-shrink-0 text-base font-bold leading-none">×</button>
                  </div>
                  <p className="text-[10px] text-gray-400 text-center">Viewing saved report · Upload a new PDF to analyze</p>
                </div>
              ) : !file ? (
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
                            Analyze
                          </button>
                        </>
                      )}
                      {appState === 'analyzing' && (
                        <span className="text-[9px] bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full font-bold flex items-center gap-1 border border-blue-100 tracking-widest">
                          <Loader2 size={8} className="animate-spin" /> ANALYZING
                        </span>
                      )}
                      {appState === 'done' && (
                        <span className="text-[9px] bg-green-50 text-green-600 border border-green-100 px-2 py-0.5 rounded-full font-bold tracking-widest">
                          DONE
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

                  {appState === 'done' && result && (
                    <div className="flex text-xs px-0.5">
                      <span className="ml-auto text-gray-400">{result.pdf_pages} page(s)</span>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Results — 3-level tree */}
          {result && (
            <div className="space-y-3">

              {/* Summary bar */}
              <div className="bg-white rounded-2xl border border-gray-200/70 px-5 py-3.5 flex items-center justify-between shadow-sm gap-4 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">

                  {/* Passed — click to filter tree to passed groups only */}
                  <button
                    onClick={() => toggleFilter('passed')}
                    title={resultFilter === 'passed' ? 'Clear filter' : 'Show only passed checks'}
                    className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-all ${
                      resultFilter === 'passed'
                        ? 'bg-green-100 border-green-300 text-green-800 font-bold ring-2 ring-green-300'
                        : totalChecksPassed > 0
                          ? 'bg-green-50 border-green-200 text-green-700 hover:ring-2 hover:ring-green-200 cursor-pointer'
                          : 'bg-gray-50 border-gray-100 text-gray-400 cursor-default'
                    }`}
                  >
                    <CheckCircle size={12} className={totalChecksPassed > 0 ? 'text-green-500' : 'text-gray-300'} />
                    <strong>{totalChecksPassed}</strong>
                    <span>passed</span>
                    {resultFilter === 'passed' && <span className="ml-0.5 text-[9px] font-black">✕</span>}
                  </button>

                  {/* Failed — click to filter tree to failed groups only */}
                  <button
                    onClick={() => toggleFilter('failed')}
                    title={resultFilter === 'failed' ? 'Clear filter' : 'Show only failed checks'}
                    className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-all ${
                      resultFilter === 'failed'
                        ? 'bg-red-100 border-red-300 text-red-800 font-bold ring-2 ring-red-300'
                        : totalChecksFailed > 0
                          ? 'bg-red-50 border-red-200 text-red-700 hover:ring-2 hover:ring-red-200 cursor-pointer'
                          : 'bg-gray-50 border-gray-100 text-gray-400 cursor-default'
                    }`}
                  >
                    <XCircle size={12} className={totalChecksFailed > 0 ? 'text-red-400' : 'text-gray-300'} />
                    <strong>{totalChecksFailed}</strong>
                    <span>failed</span>
                    {resultFilter === 'failed' && <span className="ml-0.5 text-[9px] font-black">✕</span>}
                  </button>

                  {/* Not Found — checks where required drawing info was absent */}
                  <button
                    onClick={() => toggleFilter('issues')}
                    title={resultFilter === 'issues' ? 'Clear filter' : 'Show only not-found checks'}
                    className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-all ${
                      resultFilter === 'issues'
                        ? 'bg-amber-100 border-amber-300 text-amber-800 font-bold ring-2 ring-amber-300'
                        : totalNotFound > 0
                          ? 'bg-amber-50 border-amber-200 text-amber-700 hover:ring-2 hover:ring-amber-200 cursor-pointer'
                          : 'bg-gray-50 border-gray-100 text-gray-400 cursor-default'
                    }`}
                  >
                    <AlertTriangle size={12} className={totalNotFound > 0 ? 'text-amber-500' : 'text-gray-300'} />
                    <strong>{totalNotFound}</strong>
                    <span>not found</span>
                    {resultFilter === 'issues' && <span className="ml-0.5 text-[9px] font-black">✕</span>}
                  </button>

                  {resultFilter && (
                    <span className="text-[10px] text-gray-400 italic">
                      {resultFilter === 'passed' ? 'Showing passed checks only'
                        : resultFilter === 'failed' ? 'Showing failed checks only'
                        : 'Showing not-found checks only'}
                    </span>
                  )}
                </div>

                <button onClick={downloadReport}
                  className="flex items-center gap-2 px-4 py-2 bg-slate-900 text-white text-xs font-bold rounded-xl hover:bg-slate-700 transition-colors tracking-wide shadow-sm flex-shrink-0">
                  <Download size={13} />Download Report
                </button>
              </div>

              {/* Tree view */}
              {result.sections.map(section => {
                const allGroups      = buildCheckGroups(section.issues)
                const groups         =
                  resultFilter === 'failed'
                    ? allGroups.filter(g =>
                        !g.overall?.not_found &&
                        (g.overall
                          ? g.overall.passed === false
                          : g.subItems.some(s => !s.summary.passed && !s.summary.not_found))
                      )
                  : resultFilter === 'passed'
                    ? allGroups.filter(g =>
                        g.overall
                          ? g.overall.passed === true
                          : g.subItems.some(s => s.summary.passed === true)
                      )
                  : resultFilter === 'issues'
                    ? allGroups.filter(g =>
                        g.overall?.not_found === true ||
                        (g.subItems.length > 0 && g.subItems.some(s => s.summary.not_found === true))
                      )
                  : allGroups
                if (groups.length === 0) return null
                const secCollapsed   = collapsedSections.has(section.category)
                // Stats always come from allGroups so filters don't change the numbers
                const secFailed      = allGroups.filter(g =>
                  !g.overall?.not_found &&
                  (g.overall ? g.overall.passed === false : g.subItems.some(s => !s.summary.passed && !s.summary.not_found))
                ).length
                const secNotFound    = allGroups.filter(g =>
                  g.overall?.not_found === true ||
                  (g.subItems.length > 0 && g.subItems.every(s => s.summary.not_found === true))
                ).length
                const secIssues      = allGroups.reduce(
                  (a, g) => a + g.orphanIssues.length + g.subItems.reduce((b, s) => b + s.issues.length, 0), 0
                )

                return (
                  <div key={section.category} className="bg-white rounded-2xl border border-gray-200/70 overflow-hidden shadow-sm">

                    {/* Category header */}
                    <button onClick={() => toggleSection(section.category)}
                      className="w-full px-6 py-3.5 flex items-center gap-3 hover:bg-gray-50/60 transition-colors">
                      <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                        secFailed > 0 || secIssues > 0 ? 'bg-red-400' :
                        secNotFound > 0 ? 'bg-amber-400' : 'bg-green-400'
                      }`} />
                      <span className="font-bold text-gray-900 text-sm flex-1 text-left tracking-tight">{section.title}</span>
                      <span className="text-[11px] text-gray-400">
                        {allGroups.length - secFailed - secNotFound}<span className="text-gray-300">/{allGroups.length - secNotFound}</span> checks pass
                        {secNotFound > 0 && <span className="ml-2 text-amber-500 font-semibold">· {secNotFound} not found</span>}
                        {secIssues > 0 && <span className="ml-2 text-amber-500 font-semibold">· {secIssues} issue{secIssues > 1 ? 's' : ''}</span>}
                      </span>
                      <ChevronDown size={14} className={`text-gray-400 ml-2 transition-transform ${secCollapsed ? '' : 'rotate-180'}`} />
                    </button>

                    {!secCollapsed && (
                      <div className="border-t border-gray-100 divide-y divide-gray-100">

                        {/* Level 2 — Check group */}
                        {groups.map(group => {
                          const gKey        = `${section.category}::${group.key}`
                          const gExpanded   = expandedGroups.has(gKey)
                          const gNotFound   = group.overall?.not_found === true ||
                            (group.subItems.length > 0 && group.subItems.every(s => s.summary.not_found === true))
                          const gPassed     = gNotFound
                            ? undefined
                            : group.overall
                              ? group.overall.passed
                              : group.subItems.length > 0
                                ? group.subItems.every(s => s.summary.passed === true)
                                : undefined
                          const subFailed   = group.subItems.filter(s => !s.summary.passed && !s.summary.not_found).length
                          const hasContent  = group.subItems.length > 0 || group.orphanIssues.length > 0 || (group.overall && (gNotFound || !group.overall.passed))

                          return (
                            <div key={group.key} className="bg-gray-50/20">

                              {/* Group header */}
                              <button
                                onClick={() => hasContent && toggleGroup(gKey)}
                                className={`w-full pl-10 pr-5 py-2.5 flex items-center gap-2.5 transition-colors ${hasContent ? 'hover:bg-gray-100/60 cursor-pointer' : 'cursor-default'}`}
                              >
                                <div className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center ${
                                  gPassed === true  ? 'bg-green-100' :
                                  gPassed === false ? 'bg-red-100'   :
                                  gNotFound         ? 'bg-amber-100' : 'bg-gray-100'
                                }`}>
                                  {gPassed === true  && <CheckCircle   size={11} className="text-green-600" />}
                                  {gPassed === false && <XCircle       size={11} className="text-red-500" />}
                                  {gNotFound         && <AlertTriangle size={11} className="text-amber-500" />}
                                  {gPassed === undefined && !gNotFound && <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />}
                                </div>

                                <div className="flex-1 min-w-0 text-left">
                                  <div className={`text-xs font-semibold ${
                                    gPassed === true  ? 'text-green-800' :
                                    gPassed === false ? 'text-red-800'   :
                                    gNotFound         ? 'text-amber-800' : 'text-gray-600'
                                  }`}>{group.displayName}</div>
                                  {gNotFound && group.overall && (
                                    <div className="text-[10px] text-gray-400 mt-0.5 leading-snug">
                                      {group.overall.description.replace(/^(PASS|FAIL|NOT FOUND|N\/A)\s*[—–-]\s*/i, '')}
                                    </div>
                                  )}
                                </div>

                                {group.subItems.length > 0 && (
                                  <span className="text-[10px] text-gray-400">
                                    {group.subItems.length - subFailed}/{group.subItems.length}
                                  </span>
                                )}
                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded tracking-wide ${
                                  gPassed === true  ? 'bg-green-100 text-green-700 border border-green-200' :
                                  gPassed === false ? 'bg-red-100 text-red-700 border border-red-200'       :
                                  gNotFound         ? 'bg-amber-100 text-amber-700 border border-amber-200' :
                                                      'bg-gray-100 text-gray-400 border border-gray-200'
                                }`}>
                                  {gPassed === true ? 'PASS' : gPassed === false ? 'FAIL' : gNotFound ? 'NOT FOUND' : 'N/A'}
                                </span>
                                {hasContent && (
                                  <ChevronDown size={12} className={`text-gray-400 ml-1 flex-shrink-0 transition-transform ${gExpanded ? 'rotate-180' : ''}`} />
                                )}
                              </button>

                              {/* Level 3 — Sub-items + issues */}
                              {gExpanded && hasContent && (
                                <div className="pl-16 pr-5 pb-2 space-y-0.5">

                                  {group.subItems.filter(sub =>
                                    resultFilter === 'failed' ? sub.summary.passed === false :
                                    resultFilter === 'passed' ? sub.summary.passed === true  : true
                                  ).map(sub => {
                                    const label = sub.summary.check_name?.includes(' – ')
                                      ? sub.summary.check_name.split(' – ').slice(1).join(' – ')
                                      : sub.summary.check_name ?? ''
                                    return (
                                      <div key={sub.summary.id}>
                                        <div className={`flex items-start gap-2 py-1.5 rounded-lg px-2 ${sub.summary.passed ? '' : 'bg-red-50/50'}`}>
                                          <div className={`mt-0.5 flex-shrink-0 w-3.5 h-3.5 rounded-full flex items-center justify-center ${sub.summary.passed ? 'bg-green-100' : 'bg-red-100'}`}>
                                            {sub.summary.passed
                                              ? <CheckCircle size={9} className="text-green-600" />
                                              : <XCircle    size={9} className="text-red-500" />}
                                          </div>
                                          <span className="text-[11px] font-medium text-gray-600 w-28 flex-shrink-0 truncate" title={label}>{label}</span>
                                          <span className={`text-[11px] leading-relaxed ${sub.summary.passed ? 'text-gray-400' : 'text-red-700'}`}>
                                            {sub.summary.description.replace(/^(PASS|FAIL)\s*—\s*/, '')}
                                          </span>
                                        </div>
                                        {sub.issues.map(issue => {
                                          const { cls, label: lbl } = severityBadge(issue.severity)
                                          return (
                                            <div key={issue.id} className="ml-5 flex items-start gap-2 py-1 px-2 bg-amber-50/40 rounded mt-0.5">
                                              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded flex-shrink-0 ${cls}`}>{lbl}</span>
                                              <span className="text-[11px] text-gray-600 leading-relaxed">{issue.description}</span>
                                              <span className="ml-auto text-[10px] text-gray-300 flex-shrink-0">{issue.location}</span>
                                            </div>
                                          )
                                        })}
                                      </div>
                                    )
                                  })}

                                  {group.orphanIssues.map(issue => {
                                    const { cls, label: lbl } = severityBadge(issue.severity)
                                    return (
                                      <div key={issue.id} className="flex items-start gap-2 py-1 px-2 bg-amber-50/40 rounded">
                                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded flex-shrink-0 ${cls}`}>{lbl}</span>
                                        <span className="text-[11px] text-gray-600 leading-relaxed">{issue.description}</span>
                                        <span className="ml-auto text-[10px] text-gray-300 flex-shrink-0">{issue.location}</span>
                                      </div>
                                    )
                                  })}

                                  {group.subItems.length === 0 && group.overall && group.orphanIssues.length === 0 && (
                                    <div className={`text-[11px] leading-relaxed py-1 px-2 rounded ${
                                      group.overall.passed ? 'text-green-700' :
                                      gNotFound            ? 'text-amber-700' : 'text-red-700'
                                    }`}>
                                      {group.overall.description.replace(/^(PASS|FAIL|N\/A|NOT FOUND)\s*—\s*/, '')}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          </>}{/* end dashboard view */}

        </div>
      </div>
    </div>
  )
}
