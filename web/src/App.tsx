import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import {
  LayoutDashboard, History, HelpCircle,
  FileText, CheckCircle, AlertTriangle,
  Download, Loader2, ChevronLeft, ChevronRight, ChevronDown,
  XCircle, Save, Pencil, Paperclip, RefreshCw, Highlighter,
  ListChecks, Plus, Trash2,
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
interface CheckDef {
  domain: string
  key: string
  display_name: string
  description: string
  prompt: string
  pass: string
  not_found: string
  builtin: boolean
  user_defined?: boolean
  requires_vision?: boolean
  images?: string[]     // reference images stored per check, sent to the vision model
}
interface CheckDomain {
  key: string
  title: string
  coming_soon: boolean
}
interface ExtractField {
  key: string
  label: string
  source: string
  description: string
  kind: string
}
interface ChecksData {
  checks: CheckDef[]
  domains: CheckDomain[]
}

type AppState    = 'idle' | 'ready' | 'analyzing' | 'done' | 'error'
type ResultFilter = null | 'passed' | 'failed' | 'issues'
type ActiveView  = 'dashboard' | 'history' | 'definerules'

// ── Constants ────────────────────────────────────────────────
const NODES = [
  { key: 'preprocess',        label: 'Extracting PDF content',      checkKey: null },
  { key: 'spell_check',       label: 'Checking spelling & labels',  checkKey: 'spell' },
  { key: 'bend_check',        label: 'Validating bending details',  checkKey: 'bend' },
  { key: 'rebar_check',       label: 'Validating rebar specs',      checkKey: 'rebar' },
  { key: 'aggregate_results', label: 'Aggregating results',         checkKey: null },
  { key: 'return_to_ui',      label: 'Preparing report',            checkKey: null },
]

type CheckOption = { key: string; label: string; color: string; comingSoon: boolean }

type NodeSectionCheck = {
  key: string
  title: string
  requiresOverviewPlan?: boolean
  requiresSteelList?: boolean
}
const NAV = [
  { icon: LayoutDashboard, label: 'Dashboard',     view: 'dashboard'   as ActiveView },
  { icon: History,         label: 'Check History', view: 'history'     as ActiveView },
  { icon: ListChecks,      label: 'Define Rules',  view: 'definerules' as ActiveView },
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
  spell:  'Spelling & Title Block',
  bend:   'Bending & Schedule',
  rebar:  'Rebar Labels & Dims',
  custom: 'Custom Checks',  // legacy history entries only
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
  const [steelListFile,    setSteelListFile]    = useState<File | null>(null)
  const [overviewPlanFile, setOverviewPlanFile] = useState<File | null>(null)
  const [result, setResult]             = useState<AnalysisResult | null>(null)
  const [errorMsg, setErrorMsg]         = useState('')
  const [isDragging, setIsDragging]     = useState(false)
  const [doneNodes, setDoneNodes]       = useState<string[]>([])
  const [activeNode, setActiveNode]     = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen]           = useState(true)
  const [enabledSubChecks, setEnabledSubChecks] = useState<Record<string, string[]>>({})
  const [expandedCheckCategories, setExpandedCheckCategories] = useState<Set<string>>(new Set())
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set())
  const [expandedGroups,    setExpandedGroups]    = useState<Set<string>>(new Set())
  const [resultFilter,      setResultFilter]      = useState<ResultFilter>(null)
  const [activeView,        setActiveView]        = useState<ActiveView>('dashboard')
  const [historyEntries,    setHistoryEntries]    = useState<HistoryEntry[]>(() => loadHistory())
  const [viewingEntry,           setViewingEntry]           = useState<HistoryEntry | null>(null)
  const [checksData,      setChecksData]      = useState<ChecksData | null>(null)
  const [checksLoading,   setChecksLoading]   = useState(false)
  const [checksLoadError, setChecksLoadError] = useState<string | null>(null)
  const [checkDrafts,     setCheckDrafts]     = useState<Record<string, CheckDef>>({})
  const [expandedChecks,  setExpandedChecks]  = useState<Set<string>>(new Set())
  const [checkSaving,     setCheckSaving]     = useState<string | null>(null)  // "domain::key" being saved
  const [checkErrors,     setCheckErrors]     = useState<Record<string, string>>({})
  const [pendingImages,   setPendingImages]   = useState<Record<string, File[]>>({})  // images to upload on Save, keyed by draft id
  const [extractionFields, setExtractionFields] = useState<ExtractField[]>([])
  const [extractionFieldsOpen, setExtractionFieldsOpen] = useState(false)
  const [annotating,             setAnnotating]             = useState(false)
  const inputRef           = useRef<HTMLInputElement>(null)
  const steelListInputRef  = useRef<HTMLInputElement>(null)
  const overviewPlanInputRef = useRef<HTMLInputElement>(null)

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

  // Auto-enable / disable overview_plan_check when the overview plan file changes
  useEffect(() => {
    setEnabledSubChecks(prev => {
      const spell = prev.spell ?? []
      if (overviewPlanFile && !spell.includes('overview_plan_check')) {
        return { ...prev, spell: [...spell, 'overview_plan_check'] }
      }
      if (!overviewPlanFile && spell.includes('overview_plan_check')) {
        return { ...prev, spell: spell.filter(k => k !== 'overview_plan_check') }
      }
      return prev
    })
  }, [overviewPlanFile])

  // Auto-enable / disable steel_list_check when the steel list file changes
  useEffect(() => {
    setEnabledSubChecks(prev => {
      const spell = prev.spell ?? []
      if (steelListFile && !spell.includes('steel_list_check')) {
        return { ...prev, spell: [...spell, 'steel_list_check'] }
      }
      if (!steelListFile && spell.includes('steel_list_check')) {
        return { ...prev, spell: spell.filter(k => k !== 'steel_list_check') }
      }
      return prev
    })
  }, [steelListFile])

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

  const deleteHistoryEntry = (id: string) => {
    setHistoryEntries(prev => {
      const next = prev.filter(e => e.id !== id)
      saveHistory(next)
      return next
    })
  }

  // ── Check definitions (built-in + custom) ───────────────────────────────
  const loadChecks = useCallback(() => {
    setChecksLoading(true)
    setChecksLoadError(null)
    fetch('/api/checks')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: ChecksData) => {
        if (!d?.domains?.length) throw new Error('Empty checks response from server')
        setChecksData(d)
      })
      .catch((err: unknown) => {
        setChecksLoadError(err instanceof Error ? err.message : 'Failed to load checks')
      })
      .finally(() => setChecksLoading(false))
  }, [])

  const loadExtractionFields = useCallback(() => {
    fetch('/api/extraction-fields')
      .then(r => r.json())
      .then((d: { fields?: ExtractField[] }) => setExtractionFields(d.fields ?? []))
      .catch(() => {})
  }, [])

  // Load on mount; refresh when Define Rules is opened; retry Dashboard if prior load failed.
  useEffect(() => { loadChecks() }, [loadChecks])
  useEffect(() => {
    if (activeView === 'definerules') {
      loadChecks()
      loadExtractionFields()
    }
  }, [activeView, loadChecks, loadExtractionFields])
  useEffect(() => {
    if (activeView === 'dashboard' && !checksData && !checksLoading && !checksLoadError) {
      loadChecks()
    }
  }, [activeView, checksData, checksLoading, checksLoadError, loadChecks])

  const checkOptions: CheckOption[] = useMemo(() =>
    (checksData?.domains ?? []).map(d => ({
      key: d.key,
      label: d.title,
      color: d.key === 'spell' ? 'gray' : d.key === 'bend' ? 'purple' : 'blue',
      comingSoon: d.coming_soon,
    })),
    [checksData],
  )

  const nodeSections: { key: string; title: string; checks: NodeSectionCheck[] }[] = useMemo(() => {
    if (!checksData) return []
    return checksData.domains.map(d => ({
      key: d.key,
      title: d.title,
      checks: checksData.checks
        .filter(c => c.domain === d.key)
        .map(c => ({
          key: c.key,
          title: c.display_name,
          ...(c.key === 'overview_plan_check' ? { requiresOverviewPlan: true } : {}),
          ...(c.key === 'steel_list_check' ? { requiresSteelList: true } : {}),
        })),
    }))
  }, [checksData])

  useEffect(() => {
    if (!checksData) return
    setEnabledSubChecks(prev => {
      const total = Object.values(prev).reduce((n, arr) => n + arr.length, 0)
      if (total > 0) return prev
      return Object.fromEntries(
        checksData.domains.map(d => {
          const keys = checksData.checks
            .filter(c => c.domain === d.key)
            .filter(c => c.key !== 'overview_plan_check' && c.key !== 'steel_list_check')
            .map(c => c.key)
          return [d.key, d.coming_soon ? [] : keys]
        }),
      )
    })
    setExpandedCheckCategories(prev => (prev.size > 0 ? prev : new Set(['spell'])))
  }, [checksData])

  const ckey = (c: { domain: string; key: string }) => `${c.domain}::${c.key}`

  const startEdit = (c: CheckDef) => {
    setCheckDrafts(prev => ({ ...prev, [ckey(c)]: { ...c } }))
    setExpandedChecks(prev => new Set([...prev, ckey(c)]))
  }
  const cancelEdit = (id: string) => {
    setCheckDrafts(prev => { const n = { ...prev }; delete n[id]; return n })
    setCheckErrors(prev => { const n = { ...prev }; delete n[id]; return n })
    setPendingImages(prev => { const n = { ...prev }; delete n[id]; return n })
  }
  const updateDraft = (id: string, patch: Partial<CheckDef>) =>
    setCheckDrafts(prev => ({ ...prev, [id]: { ...prev[id], ...patch } }))

  const saveCheck = async (id: string) => {
    const draft = checkDrafts[id]
    if (!draft) return
    const original = checksData?.checks.find(c => ckey(c) === id)
    const isUserDefined = draft.user_defined ?? !draft.builtin
    const promptToSend = isUserDefined ? (draft.description || draft.prompt) : draft.prompt
    if (!draft.display_name.trim()) { setCheckErrors(p => ({ ...p, [id]: 'Display name is required' })); return }
    if (isUserDefined && !draft.description.trim()) {
      setCheckErrors(p => ({ ...p, [id]: 'Description is required' })); return
    }
    if (!isUserDefined && !!original?.prompt?.trim() && !draft.prompt.trim()) {
      setCheckErrors(p => ({ ...p, [id]: 'Check prompt is required' })); return
    }
    const pending = pendingImages[id] ?? []
    const hasImages = (draft.images?.length ?? 0) > 0 || pending.length > 0
    setCheckSaving(id)
    setCheckErrors(p => { const n = { ...p }; delete n[id]; return n })
    try {
      const res = await fetch('/api/checks', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          domain: draft.domain, key: draft.builtin ? draft.key : (draft.key || null),
          display_name: draft.display_name, description: draft.description,
          prompt: promptToSend, pass_text: draft.pass, not_found_text: draft.not_found,
          // Attached reference images force vision — they can only be read visually.
          requires_vision: (draft.requires_vision ?? false) || hasImages,
        }),
      })
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`
        setCheckErrors(p => ({ ...p, [id]: String(detail) })); return
      }
      const body = await res.json().catch(() => ({})) as { check?: CheckDef }
      let saved = body.check

      // Upload newly attached reference images to the saved check.
      let uploadErr: string | null = null
      if (saved && pending.length) {
        const remaining: File[] = []
        for (const f of pending) {
          if (uploadErr) { remaining.push(f); continue }
          try {
            const fd = new FormData()
            fd.append('file', f)
            const up = await fetch(`/api/checks/${saved.domain}/${saved.key}/images`, { method: 'POST', body: fd })
            if (!up.ok) {
              const detail = (await up.json().catch(() => ({}))).detail ?? `HTTP ${up.status}`
              uploadErr = `Image "${f.name}": ${detail}`
              remaining.push(f)
            } else {
              const upBody = await up.json().catch(() => ({})) as { check?: CheckDef }
              if (upBody.check) saved = upBody.check
            }
          } catch {
            uploadErr = `Image "${f.name}" could not be uploaded`
            remaining.push(f)
          }
        }
        setPendingImages(prev => remaining.length
          ? { ...prev, [id]: remaining }
          : (() => { const n = { ...prev }; delete n[id]; return n })())
      }

      if (saved) {
        setChecksData(prev => {
          if (!prev) return prev
          if (id.startsWith('new::')) {
            const savedId = ckey(saved)
            if (prev.checks.some(c => ckey(c) === savedId)) return prev
            return { ...prev, checks: [...prev.checks, saved] }
          }
          return {
            ...prev,
            checks: prev.checks.map(c => (ckey(c) === id ? { ...c, ...saved } : c)),
          }
        })
      }
      if (saved && id.startsWith('new::')) {
        // A newly created check starts enabled in the Dashboard check list.
        const { domain: savedDomain, key: savedKey } = saved
        setEnabledSubChecks(prev => {
          const current = prev[savedDomain] ?? []
          return current.includes(savedKey)
            ? prev
            : { ...prev, [savedDomain]: [...current, savedKey] }
        })
      }
      if (uploadErr) {
        // Check saved but at least one image failed — keep the editor open so
        // the remaining pending images and the error stay visible.
        if (saved) updateDraft(id, { images: saved.images ?? [], requires_vision: saved.requires_vision })
        setCheckErrors(p => ({ ...p, [id]: `Check saved, but image upload failed — ${uploadErr}` }))
        return
      }
      setCheckDrafts(prev => { const n = { ...prev }; delete n[id]; return n })
    } catch (err) {
      setCheckErrors(p => ({
        ...p,
        [id]: err instanceof Error
          ? err.message
          : 'Could not reach backend — run start_backend.bat on port 8001',
      }))
    } finally {
      setCheckSaving(null)
    }
  }

  const deleteCheck = async (c: CheckDef) => {
    await fetch(`/api/checks/${c.domain}/${c.key}`, { method: 'DELETE' })
    setEnabledSubChecks(prev => ({
      ...prev,
      [c.domain]: (prev[c.domain] ?? []).filter(k => k !== c.key),
    }))
    loadChecks()
  }

  const addCheck = (domain = 'spell') => {
    const id = `new::${domain}`
    setCheckDrafts(prev => ({ ...prev, [id]: {
      domain, key: '', display_name: '', description: '',
      prompt: '', pass: 'PASS', not_found: 'NOT FOUND', builtin: false, user_defined: true,
      requires_vision: false, images: [],
    } }))
    setExpandedChecks(prev => new Set([...prev, id]))
  }

  const toggleCheckExpanded = (id: string) =>
    setExpandedChecks(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })

  // ── Reference images (attached per check, sent to the vision model) ──────
  const CHECK_IMG_MAX = 5
  const CHECK_IMG_MAX_MB = 5

  const addPendingImages = (id: string, draft: CheckDef, files: FileList | null) => {
    if (!files?.length) return
    const already = (draft.images?.length ?? 0) + (pendingImages[id]?.length ?? 0)
    const accepted: File[] = []
    let err: string | null = null
    for (const f of Array.from(files)) {
      if (already + accepted.length >= CHECK_IMG_MAX) { err = `A check can have at most ${CHECK_IMG_MAX} images`; break }
      if (!/\.(png|jpe?g|gif|webp)$/i.test(f.name)) { err = `"${f.name}" is not a supported image (png / jpg / gif / webp)`; continue }
      if (f.size > CHECK_IMG_MAX_MB * 1024 * 1024) { err = `"${f.name}" exceeds the ${CHECK_IMG_MAX_MB} MB limit`; continue }
      accepted.push(f)
    }
    if (accepted.length) {
      setPendingImages(prev => ({ ...prev, [id]: [...(prev[id] ?? []), ...accepted] }))
      updateDraft(id, { requires_vision: true })  // images require the vision model
    }
    if (err) setCheckErrors(p => ({ ...p, [id]: err! }))
  }

  const removePendingImage = (id: string, idx: number) =>
    setPendingImages(prev => ({ ...prev, [id]: (prev[id] ?? []).filter((_, i) => i !== idx) }))

  const deleteSavedImage = async (id: string, draft: CheckDef, name: string) => {
    const res = await fetch(
      `/api/checks/${draft.domain}/${draft.key}/images/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    )
    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`
      setCheckErrors(p => ({ ...p, [id]: String(detail) })); return
    }
    const body = await res.json().catch(() => ({})) as { check?: CheckDef }
    const images = body.check?.images ?? (draft.images ?? []).filter(n => n !== name)
    updateDraft(id, { images })
    setChecksData(prev => prev
      ? { ...prev, checks: prev.checks.map(c => (ckey(c) === id ? { ...c, images } : c)) }
      : prev)
  }

  const checkImageUrl = (c: { domain: string; key?: string }, name: string) =>
    `/api/checks/${c.domain}/${c.key}/images/${encodeURIComponent(name)}`

  // Editable form for a check draft (new custom or an existing check being edited).
  const _lbl = 'text-[10px] font-bold uppercase tracking-wider text-gray-400'
  const _inp = 'mt-1 w-full text-[12px] text-gray-700 bg-white border border-gray-200 rounded-lg px-2.5 py-2 focus:outline-none focus:ring-1 focus:ring-blue-300 focus:border-blue-300'
  const renderCheckFields = (id: string, draft: CheckDef) => {
    const saving = checkSaving === id
    const err = checkErrors[id]
    const isNew = id.startsWith('new::')
    const isUserDefined = draft.user_defined ?? !draft.builtin
    const original = checksData?.checks.find(c => ckey(c) === id)
    const showPrompt = !isUserDefined && !!original?.prompt?.trim()
    return (
      <div className="space-y-3">
        {err && (
          <div className="px-3 py-2 bg-red-50 border border-red-100 rounded-lg text-[11px] text-red-600 font-medium flex items-center gap-1.5">
            <XCircle size={11} className="flex-shrink-0" />{err}
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className={_lbl}>Display Name</span>
            <input value={draft.display_name} onChange={e => updateDraft(id, { display_name: e.target.value })}
              placeholder="e.g. Scale present" className={_inp} />
          </label>
          {isNew && (
            <label className="block">
              <span className={_lbl}>Category</span>
              <select
                value={draft.domain}
                onChange={e => updateDraft(id, { domain: e.target.value })}
                className={_inp}
              >
                {(checksData?.domains ?? []).map(d => (
                  <option key={d.key} value={d.key} disabled={d.coming_soon} className={d.coming_soon ? 'text-gray-300' : ''}>
                    {d.title}{d.coming_soon ? ' — Coming soon' : ''}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <label className="block">
          <span className={_lbl}>
            {isUserDefined ? 'Description — what the AI should check' : 'Description'}
          </span>
          <textarea value={draft.description} onChange={e => updateDraft(id, { description: e.target.value })}
            rows={isUserDefined ? 5 : 3}
            placeholder={isUserDefined
              ? "e.g. Verify a scale label like 'M 1:50' is present in the title block; report an error if it is missing."
              : 'Short summary of what this check verifies'}
            className={`${_inp} leading-relaxed resize-y`} />
        </label>
        {isUserDefined && extractionFields.length > 0 && (
          <div className="rounded-lg border border-blue-100 bg-blue-50/50 overflow-hidden">
            <button
              type="button"
              onClick={() => setExtractionFieldsOpen(v => !v)}
              className="w-full px-3 py-2.5 flex items-center gap-2 text-left hover:bg-blue-50 transition-colors"
            >
              <ChevronDown size={12} className={`text-blue-500 flex-shrink-0 transition-transform ${extractionFieldsOpen ? 'rotate-180' : ''}`} />
              <span className="text-[11px] font-bold text-blue-800">
                Available PDF extraction fields ({extractionFields.length})
              </span>
              <span className="text-[10px] text-blue-600 ml-auto">reference for your rule</span>
            </button>
            {extractionFieldsOpen && (
              <div className="border-t border-blue-100 px-3 py-2 max-h-52 overflow-auto space-y-2">
                <p className="text-[10px] text-blue-700 leading-relaxed">
                  Backend pre-extracts these values from the PDF. Reference field keys in [brackets] in your description
                  (e.g. [drawing.element_code_top_left] vs [drawing.element_code_from_title]).
                </p>
                {(['drawing', 'steel_list', 'overview_plan'] as const).map(source => {
                  const items = extractionFields.filter(f => f.source === source)
                  if (!items.length) return null
                  const title = source === 'drawing' ? 'Drawing PDF' : source === 'steel_list' ? 'Steel list PDF' : 'Overview plan PDF'
                  return (
                    <div key={source}>
                      <p className="text-[10px] font-bold uppercase tracking-wider text-blue-500">{title}</p>
                      <ul className="mt-1 space-y-0.5">
                        {items.map(f => (
                          <li key={f.key} className="text-[10px] text-gray-600 leading-snug">
                            <span className="font-mono text-blue-700">[{f.key}]</span>
                            {' '}{f.label}
                            {f.kind !== 'scalar' && (
                              <span className="text-gray-400"> · {f.kind}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
        {!isUserDefined && (showPrompt ? (
          <label className="block">
            <span className={_lbl}>Check Prompt — describe what the AI must verify</span>
            <textarea value={draft.prompt} onChange={e => updateDraft(id, { prompt: e.target.value })} rows={6}
              placeholder="e.g. Verify a scale label like 'M 1:50' is present in the title block. Report it as an error if missing."
              className={`${_inp} font-mono leading-relaxed resize-y`} />
          </label>
        ) : (
          <p className="text-[10px] text-gray-400 italic">
            This is a built-in computed check — its logic is in code, so there is no editable prompt.
          </p>
        ))}
        {isUserDefined && (() => {
          const pendingList = pendingImages[id] ?? []
          const savedList = draft.images ?? []
          return (
            <div className="rounded-lg border border-gray-100 bg-gray-50 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-bold text-gray-600">Reference Images</span>
                <span className="text-[10px] text-gray-400 hidden sm:inline">
                  sent to the vision AI with this rule · max {CHECK_IMG_MAX} · png / jpg / gif / webp ≤ {CHECK_IMG_MAX_MB} MB
                </span>
                <label className="ml-auto flex items-center gap-1 px-2.5 py-1 bg-white border border-gray-200 rounded-lg text-[10px] font-bold text-gray-600 hover:border-blue-300 hover:text-blue-600 cursor-pointer transition-colors flex-shrink-0">
                  <Paperclip size={10} /> Attach
                  <input
                    type="file" accept=".png,.jpg,.jpeg,.gif,.webp" multiple className="hidden"
                    onChange={e => { addPendingImages(id, draft, e.target.files); e.target.value = '' }}
                  />
                </label>
              </div>
              {savedList.length || pendingList.length ? (
                <div className="flex flex-wrap gap-2">
                  {savedList.map(name => (
                    <div key={name} className="relative w-20">
                      <img
                        src={checkImageUrl(draft, name)} alt={name}
                        className="w-20 h-20 object-cover rounded-lg border border-gray-200 bg-white"
                      />
                      <button
                        onClick={() => deleteSavedImage(id, draft, name)} title="Remove image"
                        className="absolute -top-1.5 -right-1.5 w-[18px] h-[18px] flex items-center justify-center bg-white border border-gray-200 rounded-full text-red-500 hover:bg-red-50 hover:border-red-200 shadow-sm"
                      >
                        <Trash2 size={9} />
                      </button>
                      <p className="text-[9px] text-gray-400 truncate mt-0.5" title={name}>{name}</p>
                    </div>
                  ))}
                  {pendingList.map((f, i) => (
                    <div key={`${f.name}-${i}`} className="relative w-20">
                      <div className="w-20 h-20 flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-blue-300 bg-blue-50/50 px-1">
                        <Paperclip size={12} className="text-blue-400" />
                        <span className="text-[8px] text-blue-600 font-semibold text-center break-all leading-tight max-h-8 overflow-hidden">{f.name}</span>
                        <span className="text-[8px] text-blue-400">uploads on Save</span>
                      </div>
                      <button
                        onClick={() => removePendingImage(id, i)} title="Remove image"
                        className="absolute -top-1.5 -right-1.5 w-[18px] h-[18px] flex items-center justify-center bg-white border border-gray-200 rounded-full text-red-500 hover:bg-red-50 hover:border-red-200 shadow-sm"
                      >
                        <Trash2 size={9} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[10px] text-gray-400 italic">
                  No images attached. Attach example crops or annotated snippets to show the AI exactly what this rule refers to.
                </p>
              )}
            </div>
          )
        })()}
        {(() => {
          const hasImages = (draft.images?.length ?? 0) > 0 || (pendingImages[id]?.length ?? 0) > 0
          const isVision = (draft.requires_vision ?? false) || hasImages
          const canToggle = isUserDefined && !hasImages
          const borderCls = isVision ? 'border-amber-200 bg-amber-50' : 'border-gray-100 bg-gray-50'
          const labelCls  = isVision ? 'text-amber-800' : 'text-gray-600'
          const noteCls   = isVision ? 'text-amber-700' : 'text-gray-500'
          return (
            <div className={`rounded-lg border p-3 space-y-2 ${borderCls}`}>
              <label className={`flex items-center gap-2.5 select-none ${canToggle ? 'cursor-pointer' : 'cursor-default'}`}>
                <input
                  type="checkbox"
                  checked={isVision}
                  disabled={!canToggle}
                  onChange={canToggle ? e => updateDraft(id, { requires_vision: e.target.checked }) : undefined}
                  className={`w-3.5 h-3.5 rounded ${canToggle ? 'accent-amber-500 cursor-pointer' : 'cursor-default opacity-60'}`}
                />
                <span className={`text-[11px] font-bold ${labelCls}`}>
                  Requires Vision
                  {isVision
                    ? <span className="ml-1.5 font-normal">(uses smarter model · higher cost)</span>
                    : <span className="ml-1.5 font-normal">(text-only · cheaper &amp; faster)</span>
                  }
                </span>
                {!isUserDefined && (
                  <span className="ml-auto text-[10px] text-gray-400">read-only for built-in checks</span>
                )}
                {isUserDefined && hasImages && (
                  <span className="ml-auto text-[10px] text-amber-600">auto-enabled — reference images attached</span>
                )}
              </label>
              <p className={`text-[10px] leading-relaxed pl-[22px] ${noteCls}`}>
                {isVision
                  ? <>
                      <span className="font-semibold">Enabled</span> — the AI receives the full rendered PDF
                      {hasImages && <> plus this rule's reference images</>} and uses{' '}
                      <span className="font-mono">claude-sonnet-4-6</span> to read values directly from graphical views
                      (cross-sections, dimension lines, narrow table columns that text extraction may drop).
                    </>
                  : <>
                      <span className="font-semibold">Disabled</span> — the AI runs on{' '}
                      <span className="font-mono">claude-haiku-4-5</span> with extracted text only.
                      {isUserDefined && ' Enable if the check needs to read from cross-section views, dimension annotations, or multi-column tables.'}
                    </>
                }
              </p>
            </div>
          )
        })()}
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className={_lbl}>Pass message</span>
            <input value={draft.pass} onChange={e => updateDraft(id, { pass: e.target.value })} className={_inp} />
          </label>
          <label className="block">
            <span className={_lbl}>Not-found message</span>
            <input value={draft.not_found} onChange={e => updateDraft(id, { not_found: e.target.value })} className={_inp} />
          </label>
        </div>
        <div className="flex items-center gap-2 pt-1">
          <button onClick={() => saveCheck(id)} disabled={saving}
            className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-[11px] font-bold rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors">
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button onClick={() => cancelEdit(id)}
            className="px-4 py-2 text-[11px] font-semibold text-gray-500 hover:text-gray-700 rounded-lg hover:bg-gray-100 transition-colors">
            Cancel
          </button>
          {draft.builtin && (
            <span className="text-[10px] text-gray-400 ml-auto">Built-in check · editing its .md wording/prompt</span>
          )}
        </div>
      </div>
    )
  }

  const enabledChecks = checkOptions
    .filter(o => !o.comingSoon && (enabledSubChecks[o.key] ?? []).length > 0)
    .map(o => o.key)

  const toggleSubCheck = (categoryKey: string, subKey: string) => {
    setEnabledSubChecks(prev => {
      const current = prev[categoryKey] ?? []
      const next = current.includes(subKey)
        ? current.filter(k => k !== subKey)
        : [...current, subKey]
      return { ...prev, [categoryKey]: next }
    })
  }

  const toggleAllInCategory = (categoryKey: string) => {
    setEnabledSubChecks(prev => {
      const allKeys = nodeSections.find(s => s.key === categoryKey)?.checks.map(c => c.key) ?? []
      const current = prev[categoryKey] ?? []
      const allEnabled = allKeys.length > 0 && allKeys.every(k => current.includes(k))
      return { ...prev, [categoryKey]: allEnabled ? [] : allKeys }
    })
  }

  const toggleCheckCategoryExpanded = (key: string) => {
    setExpandedCheckCategories(prev => {
      const next = new Set(prev); next.has(key) ? next.delete(key) : next.add(key); return next
    })
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
    const subChecksPayload = Object.fromEntries(
      enabledChecks.map(cat => [cat, enabledSubChecks[cat] ?? []])
    )
    form.append('sub_checks', JSON.stringify(subChecksPayload))
    if (steelListFile)    form.append('steel_list',    steelListFile)
    if (overviewPlanFile) form.append('overview_plan', overviewPlanFile)

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
    setFile(null); setSteelListFile(null); setOverviewPlanFile(null)
    setResult(null); setDoneNodes([]); setActiveNode(null)
    setViewingEntry(null); setErrorMsg(''); setAppState('idle')
    if (inputRef.current) inputRef.current.value = ''
    if (steelListInputRef.current) steelListInputRef.current.value = ''
    if (overviewPlanInputRef.current) overviewPlanInputRef.current.value = ''
  }

  // Send the original PDF + result to the backend, which anchors each failed
  // finding in the drawing as a highlight/comment, and download the result.
  const downloadAnnotatedPdf = async () => {
    if (!file || !result || annotating) return
    setAnnotating(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('result', JSON.stringify(result))
      const res = await fetch('/api/annotate', { method: 'POST', body: form })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { detail = (await res.json()).detail ?? detail } catch { /* non-JSON */ }
        throw new Error(detail)
      }
      const blob = await res.blob()
      const a = Object.assign(document.createElement('a'), {
        href:     URL.createObjectURL(blob),
        download: `${(file.name ?? 'drawing').replace(/\.pdf$/i, '')}_annotated.pdf`,
      })
      a.click(); URL.revokeObjectURL(a.href)
    } catch (err) {
      setErrorMsg(`Could not build annotated PDF: ${String(err)}`)
      setAppState('error')
    } finally {
      setAnnotating(false)
    }
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
              {activeView === 'history' ? 'Check History'
                : activeView === 'definerules' ? 'Define Rules'
                : 'Dashboard'}
            </h1>
            <p className="text-[11px] text-gray-400 mt-0.5 tracking-wide">
              {activeView === 'history'
                ? `${historyEntries.length} of ${HISTORY_MAX} recent analyses stored`
                : activeView === 'definerules'
                  ? 'View & edit every QA check · Add your own .md rules that run during analysis'
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
                      checkOptions.find(o => o.key === c)?.label ?? c
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
                          <button
                            onClick={() => deleteHistoryEntry(entry.id)}
                            title="Delete this entry"
                            className="flex-shrink-0 w-8 h-8 flex items-center justify-center text-gray-300 hover:text-red-500 hover:bg-red-50 rounded-xl transition-colors self-center">
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </>
              )}
            </div>
          )}

          {/* ── Define Rules view ───────────────────────── */}
          {activeView === 'definerules' && (
            <div className="space-y-4">

              {/* Header */}
              <div className="bg-white rounded-2xl border border-gray-200/70 px-6 py-4 shadow-sm flex items-center gap-4">
                <div className="w-9 h-9 rounded-xl bg-blue-50 border border-blue-100 flex items-center justify-center flex-shrink-0">
                  <ListChecks size={16} className="text-blue-500" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-bold text-gray-800">QA Check Rules</p>
                  <p className="text-[11px] text-gray-400 mt-0.5">
                    Every check is a Markdown rule. Edit any check&apos;s wording or prompt, or add your own
                    to a category — new rules run by AI during analysis and appear on the Dashboard like any other check.
                  </p>
                </div>
                <button onClick={() => addCheck('spell')}
                  className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-xs font-bold rounded-xl hover:bg-blue-700 transition-colors flex-shrink-0">
                  <Plus size={13} /> Add Check
                </button>
              </div>

              {checksLoading && !checksData ? (
                <div className="flex items-center justify-center py-20 gap-2 text-gray-400">
                  <Loader2 size={18} className="animate-spin" /><span className="text-sm">Loading…</span>
                </div>
              ) : checksLoadError && !checksData ? (
                <div className="rounded-xl border border-red-100 bg-red-50 px-5 py-4 space-y-2">
                  <p className="text-[12px] font-semibold text-red-600">
                    Could not load checks — {checksLoadError}
                  </p>
                  <p className="text-[11px] text-red-500/80 leading-relaxed">
                    Start the backend on port 8001 (<span className="font-mono">start_backend.bat</span>) then retry.
                  </p>
                  <button
                    onClick={() => { setChecksLoadError(null); loadChecks() }}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-red-200 text-red-600 text-[11px] font-bold rounded-lg hover:bg-red-100/50 transition-colors"
                  >
                    <RefreshCw size={11} /> Retry
                  </button>
                </div>
              ) : (
                <>
                  {/* New check draft */}
                  {Object.entries(checkDrafts).filter(([id]) => id.startsWith('new::')).map(([id, draft]) => (
                    <div key={id} className="bg-white rounded-2xl border-2 border-blue-200 shadow-sm px-5 py-4">
                      <div className="flex items-center gap-2 mb-3">
                        <span className="w-5 h-5 rounded-md bg-blue-100 flex items-center justify-center"><Plus size={12} className="text-blue-600" /></span>
                        <span className="text-[13px] font-bold text-gray-800">New Check</span>
                      </div>
                      {renderCheckFields(id, draft)}
                    </div>
                  ))}

                  {/* Checks grouped by domain */}
                  {(checksData?.domains ?? []).map(domain => {
                    const list = (checksData?.checks ?? []).filter(c => c.domain === domain.key)
                    if (!list.length) return null
                    const comingSoon = domain.coming_soon
                    return (
                      <div key={domain.key} className="space-y-2">
                        <div className="flex items-center gap-2 px-1 pt-1">
                          <span className={`text-[11px] font-black uppercase tracking-widest ${comingSoon ? 'text-gray-300' : 'text-gray-400'}`}>{domain.title}</span>
                          <span className="text-[10px] text-gray-300">{list.length}</span>
                          {comingSoon && (
                            <span className="text-[9px] px-1.5 py-0.5 bg-amber-100 text-amber-600 border border-amber-200 rounded-full font-bold">Coming soon</span>
                          )}
                        </div>
                        <div className={comingSoon ? 'space-y-2 opacity-50 pointer-events-none select-none' : 'space-y-2'}>
                        {list.map(c => {
                          const id = ckey(c)
                          const draft = checkDrafts[id]
                          const expanded = expandedChecks.has(id)
                          return (
                            <div key={id} className="bg-white rounded-2xl border border-gray-200/70 overflow-hidden shadow-sm">
                              <button onClick={() => toggleCheckExpanded(id)}
                                className="w-full px-5 py-3 flex items-center gap-3 hover:bg-gray-50/60 transition-colors">
                                <ChevronDown size={13} className={`text-gray-400 transition-transform flex-shrink-0 ${expanded ? 'rotate-180' : ''}`} />
                                <span className="text-[13px] font-semibold text-gray-700 flex-1 text-left truncate">{c.display_name}</span>
                                <span className="text-[9px] font-mono text-gray-300 hidden sm:inline">{c.key}</span>
                                {c.builtin
                                  ? <span className="text-[9px] px-1.5 py-0.5 bg-gray-100 text-gray-500 border border-gray-200 rounded-full font-bold flex-shrink-0">Built-in</span>
                                  : <span className="text-[9px] px-1.5 py-0.5 bg-green-100 text-green-700 border border-green-200 rounded-full font-bold flex-shrink-0">User rule</span>}
                              </button>
                              {expanded && (
                                <div className="border-t border-gray-100 px-5 py-4">
                                  {draft ? renderCheckFields(id, draft) : (
                                    <div className="space-y-3">
                                      <div>
                                        <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Description</p>
                                        {c.description
                                          ? <p className="text-[12px] text-gray-600 mt-0.5 whitespace-pre-wrap leading-relaxed">{c.description}</p>
                                          : <p className="text-[12px] italic text-gray-300 mt-0.5">None</p>}
                                      </div>
                                      <div className={`rounded-lg border p-3 ${c.requires_vision ? 'border-amber-200 bg-amber-50' : 'border-gray-100 bg-gray-50'}`}>
                                        <p className={`text-[11px] font-bold ${c.requires_vision ? 'text-amber-800' : 'text-gray-600'}`}>
                                          Requires Vision: {c.requires_vision ? 'Yes' : 'No'}
                                          <span className="ml-1.5 font-normal">
                                            {c.requires_vision
                                              ? '(claude-sonnet-4-6 + PDF)'
                                              : '(claude-haiku-4-5, text-only)'}
                                          </span>
                                          {(c.images?.length ?? 0) > 0 && (
                                            <span className="ml-1.5 font-normal text-amber-600">· {c.images!.length} reference image{c.images!.length > 1 ? 's' : ''} attached</span>
                                          )}
                                        </p>
                                      </div>
                                      {(c.images?.length ?? 0) > 0 && (
                                        <div>
                                          <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Reference images</p>
                                          <div className="flex flex-wrap gap-2 mt-1">
                                            {c.images!.map(name => (
                                              <div key={name} className="w-16">
                                                <img
                                                  src={checkImageUrl(c, name)} alt={name}
                                                  className="w-16 h-16 object-cover rounded-lg border border-gray-200 bg-white"
                                                />
                                                <p className="text-[9px] text-gray-400 truncate mt-0.5" title={name}>{name}</p>
                                              </div>
                                            ))}
                                          </div>
                                        </div>
                                      )}
                                      <div className="grid grid-cols-2 gap-3">
                                        <div>
                                          <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Pass message</p>
                                          <p className="text-[12px] text-gray-600 mt-0.5">{c.pass || 'PASS'}</p>
                                        </div>
                                        <div>
                                          <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Not-found message</p>
                                          <p className="text-[12px] text-gray-600 mt-0.5">{c.not_found || 'NOT FOUND'}</p>
                                        </div>
                                      </div>
                                      {c.builtin && (c.prompt
                                        ? (
                                          <div>
                                            <p className="text-[10px] font-bold uppercase tracking-wider text-gray-400">Check Prompt</p>
                                            <pre className="text-[11px] text-gray-600 mt-0.5 whitespace-pre-wrap font-mono bg-gray-50 border border-gray-100 rounded-lg p-3 max-h-60 overflow-auto">{c.prompt}</pre>
                                          </div>
                                        )
                                        : (
                                          <p className="text-[10px] text-gray-400 italic">Computed check — logic is in code, no editable prompt.</p>
                                        ))}
                                      <div className="flex items-center gap-2">
                                        <button onClick={() => startEdit(c)}
                                          className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-900 text-white text-[11px] font-bold rounded-lg hover:bg-blue-600 transition-colors">
                                          <Pencil size={11} /> Edit
                                        </button>
                                        {!c.builtin && (
                                          <button onClick={() => deleteCheck(c)}
                                            className="flex items-center gap-1.5 px-3.5 py-1.5 text-[11px] font-bold text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                                            <Trash2 size={11} /> Delete
                                          </button>
                                        )}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        })}
                        </div>
                      </div>
                    )
                  })}
                </>
              )}
            </div>
          )}

          {/* ── Dashboard view ───────────────────────────── */}
          {activeView === 'dashboard' && <>

          {/* Upload + Active checks */}
          <div className="grid grid-cols-2 gap-5">

            {/* Drop zone + Supplementary Files */}
            <div className="flex flex-col gap-3">

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

              {/* Supplementary Files */}
              <div className="bg-white rounded-2xl border border-gray-200/70 p-4 flex flex-col gap-2.5 shadow-sm">
                <h2 className="text-[9px] font-bold text-gray-400 uppercase tracking-[0.12em]">Supplementary Files</h2>

                {/* Steel List */}
                <div>
                  <input ref={steelListInputRef} type="file" accept=".pdf" className="hidden"
                    onChange={e => { const f = e.target.files?.[0]; if (f) setSteelListFile(f) }} />
                  {steelListFile ? (
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-green-50 border border-green-100">
                      <FileText size={11} className="text-green-500 flex-shrink-0" />
                      <span className="text-[11px] text-green-700 truncate flex-1">{steelListFile.name}</span>
                      <button onClick={() => { setSteelListFile(null); if (steelListInputRef.current) steelListInputRef.current.value = '' }}
                        className="text-green-300 hover:text-red-400 text-sm font-bold leading-none ml-1">×</button>
                    </div>
                  ) : (
                    <button onClick={() => steelListInputRef.current?.click()}
                      className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg border border-dashed border-gray-200 hover:border-blue-200 hover:bg-blue-50/20 transition-colors text-left">
                      <Paperclip size={11} className="text-gray-300 flex-shrink-0" />
                      <span className="text-[11px] text-gray-400">Attach Steel List (PDF)</span>
                    </button>
                  )}
                </div>

                {/* Overview Plan */}
                <div>
                  <input ref={overviewPlanInputRef} type="file" accept=".pdf" className="hidden"
                    onChange={e => { const f = e.target.files?.[0]; if (f) setOverviewPlanFile(f) }} />
                  {overviewPlanFile ? (
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-green-50 border border-green-100">
                      <FileText size={11} className="text-green-500 flex-shrink-0" />
                      <span className="text-[11px] text-green-700 truncate flex-1">{overviewPlanFile.name}</span>
                      <button onClick={() => { setOverviewPlanFile(null); if (overviewPlanInputRef.current) overviewPlanInputRef.current.value = '' }}
                        className="text-green-300 hover:text-red-400 text-sm font-bold leading-none ml-1">×</button>
                    </div>
                  ) : (
                    <button onClick={() => overviewPlanInputRef.current?.click()}
                      className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg border border-dashed border-gray-200 hover:border-blue-200 hover:bg-blue-50/20 transition-colors text-left">
                      <Paperclip size={11} className="text-gray-300 flex-shrink-0" />
                      <span className="text-[11px] text-gray-400">Attach Overview Plan (PDF)</span>
                    </button>
                  )}
                </div>
              </div>

            </div>

            {/* Active checks panel */}
            <div className="bg-white rounded-2xl border border-gray-200/70 p-5 flex flex-col gap-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-[10px] font-bold text-gray-400 uppercase tracking-[0.15em]">Active Checks</h2>
                {enabledChecks.length === 0 && (
                  <span className="text-[10px] text-red-400 font-semibold">Select at least one check</span>
                )}
              </div>

              <div className="flex flex-col gap-2.5">
                {checksLoading && !checksData ? (
                  <div className="flex items-center justify-center py-8 gap-2 text-gray-400">
                    <Loader2 size={16} className="animate-spin" /><span className="text-xs">Loading checks…</span>
                  </div>
                ) : checksLoadError && !checksData ? (
                  <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 space-y-2">
                    <p className="text-[11px] font-semibold text-red-600">
                      Could not load checks — {checksLoadError}
                    </p>
                    <p className="text-[10px] text-red-500/80 leading-relaxed">
                      Start the backend on port 8001 (<span className="font-mono">start_backend.bat</span>) then retry.
                    </p>
                    <button
                      onClick={() => { setChecksLoadError(null); loadChecks() }}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-red-200 text-red-600 text-[10px] font-bold rounded-lg hover:bg-red-100/50 transition-colors"
                    >
                      <RefreshCw size={11} /> Retry
                    </button>
                  </div>
                ) : checkOptions.length === 0 ? (
                  <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3">
                    <p className="text-[11px] text-amber-700">No check categories available.</p>
                  </div>
                ) : (
                <>
                <div className="flex gap-2">
                  {checkOptions.map(({ key, label, comingSoon }) => {
                    const section = nodeSections.find(s => s.key === key)
                    if (!section) return null
                    const allSubKeys = section.checks.map(c => c.key)
                    const enabledSubs = enabledSubChecks[key] ?? []
                    const allEnabled = allSubKeys.every(k => enabledSubs.includes(k))
                    const someEnabled = enabledSubs.length > 0
                    const isExpanded = expandedCheckCategories.has(key)
                    const disabled = appState === 'analyzing'

                    if (comingSoon) {
                      return (
                        <div key={key} className="flex-1 rounded-xl overflow-hidden border border-gray-200 opacity-70 cursor-not-allowed select-none">
                          <div className="flex flex-col bg-gray-50">
                            <div className="flex items-start gap-2 px-3 pt-2.5 pb-1">
                              <span className="mt-0.5 w-3.5 h-3.5 rounded border-[1.5px] flex-shrink-0 border-gray-200 bg-white" />
                              <span className="text-[10px] font-bold leading-snug text-gray-400">{label}</span>
                            </div>
                            <div className="flex items-center px-3 pb-2 pt-0.5">
                              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none bg-amber-100 text-amber-600 border border-amber-200">
                                Coming Soon
                              </span>
                            </div>
                          </div>
                        </div>
                      )
                    }

                    return (
                      <div key={key} className={`flex-1 rounded-xl overflow-hidden border transition-all ${
                        someEnabled
                          ? isExpanded ? 'border-blue-400 shadow-md shadow-blue-100' : 'border-blue-200 shadow-sm shadow-blue-100/50'
                          : 'border-gray-200'
                      } ${disabled ? 'opacity-60' : ''}`}>
                        <div className={`flex flex-col ${someEnabled ? 'bg-blue-600' : 'bg-gray-50'}`}>
                          {/* Label + checkbox */}
                          <button
                            onClick={() => !disabled && toggleAllInCategory(key)}
                            disabled={disabled}
                            className="flex items-start gap-2 w-full px-3 pt-2.5 pb-1 text-left"
                          >
                            <span className={`mt-0.5 w-3.5 h-3.5 rounded border-[1.5px] flex-shrink-0 flex items-center justify-center transition-colors ${
                              allEnabled ? 'bg-white/25 border-white/60'
                              : someEnabled ? 'bg-white/15 border-white/40'
                              : 'bg-white border-gray-300'
                            }`}>
                              {allEnabled && (
                                <svg viewBox="0 0 10 8" className="w-2 h-1.5" fill="none">
                                  <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
                                </svg>
                              )}
                              {!allEnabled && someEnabled && (
                                <span className="w-1.5 h-0.5 bg-white/80 rounded-full block" />
                              )}
                            </span>
                            <span className={`text-[10px] font-bold leading-snug ${someEnabled ? 'text-white' : 'text-gray-500'}`}>
                              {label}
                            </span>
                          </button>
                          {/* Count + chevron */}
                          <div className="flex items-center justify-between px-3 pb-2 pt-0.5">
                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none ${
                              someEnabled ? 'bg-white/20 text-white/90' : 'bg-gray-200 text-gray-500'
                            }`}>
                              {enabledSubs.length}/{allSubKeys.length}
                            </span>
                            <button
                              onClick={() => toggleCheckCategoryExpanded(key)}
                              className={`flex items-center justify-center w-5 h-5 rounded-md transition-colors ${
                                someEnabled ? 'hover:bg-white/20 text-white/70' : 'hover:bg-gray-200 text-gray-400'
                              }`}
                            >
                              <ChevronDown size={12} className={`transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`} />
                            </button>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Sub-checks panel — full-width, below the row */}
                {checkOptions.map(({ key, label, comingSoon }) => {
                  if (comingSoon || !expandedCheckCategories.has(key)) return null
                  const section = nodeSections.find(s => s.key === key)
                  if (!section) return null
                  const enabledSubs = enabledSubChecks[key] ?? []
                  const someEnabled = enabledSubs.length > 0
                  const disabled = appState === 'analyzing'
                  return (
                    <div key={`sub-${key}`} className={`rounded-xl border overflow-hidden ${
                      someEnabled ? 'border-blue-200' : 'border-gray-200'
                    }`}>
                      {/* Panel header */}
                      <div className={`flex items-center justify-between px-3.5 py-2 border-b ${
                        someEnabled ? 'bg-blue-50 border-blue-100' : 'bg-gray-50 border-gray-100'
                      }`}>
                        <span className={`text-[9px] font-bold uppercase tracking-widest ${
                          someEnabled ? 'text-blue-500' : 'text-gray-400'
                        }`}>{label}</span>
                        <button
                          onClick={() => !disabled && toggleAllInCategory(key)}
                          className={`text-[9px] font-semibold transition-colors ${
                            someEnabled ? 'text-blue-400 hover:text-blue-600' : 'text-gray-400 hover:text-gray-600'
                          }`}
                        >
                          {enabledSubs.length === section.checks.length ? 'Deselect all' : 'Select all'}
                        </button>
                      </div>
                      {/* Sub-check list — 2-column grid */}
                      <div className="bg-white px-3 py-2.5 grid grid-cols-2 gap-x-2 gap-y-0.5">
                        {section.checks.map(check => {
                          const subOn = enabledSubs.includes(check.key)
                          const noFile = (check.key === 'overview_plan_check' && !overviewPlanFile)
                            || (check.key === 'steel_list_check' && !steelListFile)
                          const noFileTitle = check.key === 'steel_list_check' && !steelListFile
                            ? 'Upload a Steel List to enable'
                            : noFile ? 'Upload an Overview Plan to enable' : undefined
                          return (
                            <button
                              key={check.key}
                              onClick={() => !disabled && !noFile && toggleSubCheck(key, check.key)}
                              disabled={disabled || noFile}
                              title={noFileTitle}
                              className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition-colors ${
                                noFile
                                  ? 'opacity-40 cursor-not-allowed text-gray-300'
                                  : subOn
                                    ? 'text-blue-700 hover:bg-blue-50'
                                    : 'text-gray-400 hover:bg-gray-50 hover:text-gray-500'
                              }`}
                            >
                              <span className={`w-3.5 h-3.5 rounded border-[1.5px] flex-shrink-0 flex items-center justify-center transition-colors ${
                                noFile    ? 'border-gray-200 bg-white'
                                : subOn  ? 'bg-blue-500 border-blue-500'
                                          : 'border-gray-300 bg-white'
                              }`}>
                                {subOn && !noFile && (
                                  <svg viewBox="0 0 10 8" className="w-2 h-1.5" fill="none">
                                    <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                                  </svg>
                                )}
                              </span>
                              <span className="text-[10px] font-medium leading-tight truncate">{check.title}</span>
                              {noFile && <Paperclip size={9} className="text-gray-300 flex-shrink-0 ml-auto" />}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}

                </>
                )}
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
                            {checkOptions.find(o => o.key === c)?.label ?? c}
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
                  <p className="text-[11px] text-gray-200 tracking-wide">Upload a PDF to analyze</p>
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
                        <>
                          <span className="text-[9px] bg-green-50 text-green-600 border border-green-100 px-2 py-0.5 rounded-full font-bold tracking-widest">
                            DONE
                          </span>
                          <button
                            onClick={analyze}
                            disabled={enabledChecks.length === 0}
                            title={enabledChecks.length === 0 ? 'Select at least one check' : 'Run the analysis again'}
                            className="ml-1 flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white text-[11px] font-bold rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors tracking-wide shadow-sm">
                            <RefreshCw size={11} /> Re-Analyze
                          </button>
                        </>
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

                <div className="flex items-center gap-2 flex-shrink-0">
                  {file && (
                    <button onClick={downloadAnnotatedPdf}
                      disabled={annotating}
                      title="Download the PDF with each failed finding highlighted and commented in place"
                      className="flex items-center gap-2 px-4 py-2 bg-amber-500 text-white text-xs font-bold rounded-xl hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors tracking-wide shadow-sm">
                      {annotating ? <Loader2 size={13} className="animate-spin" /> : <Highlighter size={13} />}
                      {annotating ? 'Building…' : 'Annotated PDF'}
                    </button>
                  )}
                </div>
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
                                  {gPassed === true && group.overall && (
                                    <div className="text-[10px] text-green-600 mt-0.5 leading-snug">
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
