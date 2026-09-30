export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

export interface PaperListItem {
  id: string; conference: string; year: number; title: string; authors: string[]
  topic: string | null; arxiv_id: string | null; mapping_status: string | null
  analysis_status: string | null; likes: number | null; updated_at: string
}

export interface PaginatedPapers { total: number; page: number; page_size: number; items: PaperListItem[] }
export interface PaperDetail extends PaperListItem {
  detail_url: string | null; pdf_url: string | null; arxiv_url: string | null
  mapping: Record<string, unknown> | null
  analysis: { status: string; analysis_mode: string; payload: Record<string, unknown> | null; error_code: string | null; error_detail: string | null; model: string | null; source_path: string; source_sha256: string; answers: Array<{ question: string; answer: string }> } | null
  document: Record<string, unknown> | null
}
export interface Dashboard {
  papers_total: number; conferences: Record<string, number>; mappings: Record<string, number>
  analyses: Record<string, number>; documents: Record<string, number>; likes_success: number
  active_runs: Array<Record<string, unknown>>; recent_errors: Array<Record<string, unknown>>; last_import_at: string | null
}
export interface PaperFilters {
  query?: string; conference?: string; year?: number; topic?: string; mapping_status?: string
  analysis_status?: string; sort?: string; page?: number; page_size?: number
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body) headers.set("Content-Type", "application/json")
  if (init?.method && init.method !== "GET") headers.set("X-Workbench-Request", "1")
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new ApiError(payload.detail ?? `请求失败（${response.status}）`, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function getDashboard() { return api<Dashboard>("/api/dashboard") }
export function getPapers(filters: PaperFilters = {}) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => { if (value !== undefined && value !== "") params.set(key, String(value)) })
  return api<PaginatedPapers>(`/api/papers?${params}`)
}
export function getPaper(id: string) { return api<PaperDetail>(`/api/papers/${id}`) }

export interface PipelineStatus {
  analysis_runs: Array<{ id: string; status: string }>
  analysis_error?: string | null
  mapping: { status: string; exit_code: number | null }
}
export interface AnalysisConfig {
  run_id: string
  analysis_concurrency: number
  analysis_request_interval_seconds: number
  max_new_analyses_per_run: number
}
export interface PipelineAction { status: string; message: string; id?: string; external_id?: string }
export interface PipelineRun {
  id: string; external_id: string | null; run_key: string; pipeline: string; status: string
  config: Record<string, unknown>; counters: Record<string, unknown>; started_at: string | null; ended_at: string | null; created_at: string
}

export function getPipelineStatus() { return api<PipelineStatus>("/api/pipelines/status") }
export function startAnalysis(config: AnalysisConfig) { return api<PipelineAction>("/api/pipelines/analysis/start", { method: "POST", body: JSON.stringify(config) }) }
export function stopAnalysis() { return api<PipelineAction>("/api/pipelines/analysis/stop", { method: "POST" }) }
export function startMapping(retryUnresolved: boolean) { return api<PipelineAction>("/api/pipelines/mapping/start", { method: "POST", body: JSON.stringify({ retry_unresolved: retryUnresolved }) }) }
export function stopMapping() { return api<PipelineAction>("/api/pipelines/mapping/stop", { method: "POST" }) }
export function getRuns() { return api<{ items: PipelineRun[]; total: number }>("/api/runs") }

export interface PreferenceItem { id: string; kind: string; value: string; weight: number }
export interface Preferences {
  interests: PreferenceItem[]; keywords: PreferenceItem[]; weights: Record<string, number>
  recent_works: Array<{ id: string; title: string; abstract: string | null; arxiv_id: string | null; notes: string | null }>
}
export interface DocumentRecord { paper_id: string; title: string; status: string; kind: string; path: string | null; parser: string | null; parser_version: string | null; last_error: string | null }
export function getPreferences() { return api<Preferences>("/api/preferences") }
export function addInterest(kind: "interest" | "keyword", value: string, weight = 1) { return api<PreferenceItem>("/api/preferences/interests", { method: "POST", body: JSON.stringify({ kind, value, weight }) }) }
export function deleteInterest(id: string) { return api<void>(`/api/preferences/interests/${id}`, { method: "DELETE" }) }
export function updateWeights(weights: Record<string, number>) { return api<Record<string, number>>("/api/preferences/weights", { method: "PUT", body: JSON.stringify(weights) }) }
export function getDocuments() { return api<{ summary: Record<string, number>; total: number; items: DocumentRecord[] }>("/api/knowledge/documents") }
