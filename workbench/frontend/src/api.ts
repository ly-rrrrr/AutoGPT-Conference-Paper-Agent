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
export interface InfrastructureOverview {
  services: Record<"postgresql" | "milvus" | "grobid", string>
  assets: {
    current: number
    revisions: number
    chunks: number
    by_kind_status: Array<{ kind: string; status: string; count: number }>
  }
  vectors: { records: number; by_status: Record<string, number> }
  jobs: { by_status: Record<string, number> }
}
export function getPreferences() { return api<Preferences>("/api/preferences") }
export function addInterest(kind: "interest" | "keyword", value: string, weight = 1) { return api<PreferenceItem>("/api/preferences/interests", { method: "POST", body: JSON.stringify({ kind, value, weight }) }) }
export function deleteInterest(id: string) { return api<void>(`/api/preferences/interests/${id}`, { method: "DELETE" }) }
export function updateWeights(weights: Record<string, number>) { return api<Record<string, number>>("/api/preferences/weights", { method: "PUT", body: JSON.stringify(weights) }) }
export function getDocuments() { return api<{ summary: Record<string, number>; total: number; items: DocumentRecord[] }>("/api/knowledge/documents") }
export function getInfrastructureOverview() { return api<InfrastructureOverview>("/api/infrastructure/overview") }

export interface LineageOverview {
  papers_with_lineage: number
  reference_works: number
  references: number
  evidence: number
  relations: Record<string, number>
  parser: { name: string; ready: boolean }
}
export interface LineagePaper {
  id: string
  title: string
  conference: string
  year: number
  arxiv_id: string | null
  pdf_url: string | null
  reference_count: number
}
export interface LineageNode {
  id: string
  kind: "paper" | "reference_work"
  title: string
  year: number | null
  venue: string | null
  arxiv_id?: string | null
  doi?: string | null
  linked_paper_id?: string | null
  is_center: boolean
}
export interface LineageEdge {
  id: string
  source: string
  target: string
  relation_type: string
  confidence: number
  status: string
  evidence: {
    context: string
    section: string | null
    page: number | null
    coordinates: string[]
    classifier: string
    classifier_version: string
    source_path: string
    source_sha256: string
    raw_reference: string | null
  }
}
export interface LineageGraph {
  center_paper_id: string
  nodes: LineageNode[]
  edges: LineageEdge[]
  truncated: boolean
}

export function getLineageOverview() { return api<LineageOverview>("/api/lineage/overview") }
export function getLineagePapers(query = "") {
  const params = new URLSearchParams()
  if (query.trim()) params.set("query", query.trim())
  return api<{ items: LineagePaper[] }>(`/api/lineage/papers?${params}`)
}
export function getPaperLineage(id: string, relations: string[] = []) {
  const params = new URLSearchParams()
  relations.forEach((relation) => params.append("relation_type", relation))
  return api<LineageGraph>(`/api/lineage/papers/${id}?${params}`)
}
export function startLineageExtraction(id: string) {
  return api<{ status: string; run_id: string; message: string }>(
    `/api/lineage/papers/${id}/extract`,
    { method: "POST" },
  )
}

export type ResearchEpistemicStatus = "OBSERVED" | "AUTHOR_CLAIM" | "INFERRED" | "SYNTHESIZED"
export type ResearchEvidenceStance = "SUPPORTS" | "CHALLENGES" | "CONTEXT"

export interface ResearchBrief {
  id: string
  title: string
  objective: string
  scope: Record<string, unknown>
  tool_policy: Record<string, unknown>
  budget: Record<string, unknown>
  output_preferences: Record<string, unknown>
  status: string
  created_at: string
  updated_at: string
}

export interface ResearchArtifact {
  id: string
  brief_id: string
  workflow_run_id: string | null
  supersedes_artifact_id: string | null
  artifact_type: string
  status: string
  content: Record<string, unknown>
  narrative: string | null
  generator: string
  generator_version: string
  configuration: Record<string, unknown>
  uncertainty: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ResearchEvidence {
  id: string
  artifact_id: string
  paper_id: string | null
  document_asset_id: string | null
  source_kind: string
  source_uri: string
  page_number: number | null
  section_title: string | null
  quote: string | null
  locator: Record<string, unknown>
  source_sha256: string | null
  stance: ResearchEvidenceStance
}

export interface ResearchInsight {
  id: string
  artifact_id: string
  title: string
  statement: string
  why_it_matters: string
  epistemic_status: ResearchEpistemicStatus
  scope: Record<string, unknown>
  counterarguments: unknown[]
  open_questions: unknown[]
  suggested_view: Record<string, unknown>
  status: string
  created_at: string
  updated_at: string
}

export interface ResearchBriefDetail extends ResearchBrief {
  artifacts: ResearchArtifact[]
  evidence: ResearchEvidence[]
  insights: ResearchInsight[]
  dependencies: Array<{ parent_artifact_id: string; child_artifact_id: string; relation: string }>
  runs: Array<{ id: string; status: string; counters: Record<string, unknown>; started_at: string | null; ended_at: string | null }>
  coverage: {
    paper_count: number
    analysis_count: number
    document_count: number
    status: "READY" | "LIMITED" | "BLOCKED"
    blockers: string[]
    warnings: string[]
  }
  events: Array<{
    id: string
    run_id: string
    level: string
    event_type: string
    message: string
    details: Record<string, unknown>
    created_at: string
  }>
}

export interface ResearchBriefInput {
  title: string
  objective: string
  scope: Record<string, unknown>
  tool_policy: Record<string, unknown>
  budget: Record<string, unknown>
  output_preferences: Record<string, unknown>
}

export interface ResearchRuntimeStatus {
  ready: boolean
  control_plane: { name: string; status: string; detail: string }
  components: Array<{ id: string; name: string; status: string; detail: string }>
}

export function getResearchBriefs() {
  return api<{ items: ResearchBrief[]; total: number }>("/api/research/briefs")
}

export function getResearchBrief(id: string) {
  return api<ResearchBriefDetail>(`/api/research/briefs/${id}`)
}

export function createResearchBrief(payload: ResearchBriefInput) {
  return api<ResearchBrief>("/api/research/briefs", { method: "POST", body: JSON.stringify(payload) })
}

export function updateResearchBrief(id: string, payload: ResearchBriefInput) {
  return api<ResearchBrief>(`/api/research/briefs/${id}`, { method: "PUT", body: JSON.stringify(payload) })
}

export function getResearchRuntime() {
  return api<ResearchRuntimeStatus>("/api/research/runtime")
}

export function startResearchBrief(id: string) {
  return api<{ status: string; run_id: string; message: string }>(`/api/research/briefs/${id}/run`, { method: "POST" })
}

export interface CognitionOverview {
  scope: { conference: string; year: number }
  harness_version: string
  material_fingerprint: string
  coverage: {
    papers: number
    arxiv_links: number
    paper_analyses: number
    likes: number
    local_documents: number
    paper_memories: number
    cognition_artifacts: number
  }
  gaps: {
    missing_arxiv: number
    missing_analysis: number
    missing_local_document: number
  }
  latest_run: PipelineRun | null
  discovery_run: PipelineRun | null
  model_ready: boolean
  events: Array<{
    id: string
    event_type: string
    message: string
    details: Record<string, unknown>
    created_at: string
  }>
  discovery_events: Array<{
    id: string
    event_type: string
    message: string
    details: Record<string, unknown>
    created_at: string
  }>
  artifacts: Array<{
    id: string
    artifact_type: string
    status: string
    narrative: string | null
    content: {
      batch_summary?: string
      observations?: Array<{
        title: string
        statement: string
        why_investigate?: string
        paper_ids?: string[]
        alternative_explanations?: string[]
        next_questions?: string[]
      }>
      research_agenda?: Array<{
        question: string
        rationale?: string
        paper_ids?: string[]
      }>
      limitations?: string[]
    }
    scope: Record<string, unknown>
    model: string | null
    sources: Array<{ paper_id: string; title: string; arxiv_id: string | null }>
    created_at: string
  }>
  stages: Array<{
    id: string
    name: string
    status: string
    ready: number
    total: number
    detail: string
  }>
  roles: Array<{ name: string; mode: string; purpose: string }>
}

export function getCognitionOverview(conference = "CVPR", year = 2026) {
  const params = new URLSearchParams({ conference, year: String(year) })
  return api<CognitionOverview>(`/api/cognition/overview?${params}`)
}

export function prepareCognitionHarness(conference = "CVPR", year = 2026) {
  return api<{ status: string; message: string; run: PipelineRun }>("/api/cognition/prepare", {
    method: "POST",
    body: JSON.stringify({ conference, year }),
  })
}

export interface CognitionDiscoveryInput {
  conference: string
  year: number
  max_model_calls: number
  papers_per_batch: number
  max_input_chars: number
}

export function startCognitionDiscovery(payload: CognitionDiscoveryInput) {
  return api<{ status: string; run_id: string; message: string }>("/api/cognition/discovery/start", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function stopCognitionDiscovery(runId: string) {
  return api<{ status: string; message: string }>(`/api/cognition/discovery/${runId}/stop`, { method: "POST" })
}

export interface MethodInsight {
  id: string
  status: string
  title: string
  claim: string
  mechanism: string | null
  problem_pressure: string | null
  borrowed_idea: string | null
  adaptation: string | null
  domains: string[]
  transfer_targets: string[]
  counterargument: string | null
  evidence_boundary: string | null
  open_questions: string[]
  confidence: number
  sources: Array<{ paper_id: string; title: string; arxiv_id: string | null; stance: string }>
  model: string | null
  created_at: string
}

export interface AtlasOverview {
  scope: { conference: string; year: number }
  model_ready: boolean
  discovery_artifacts: number
  consumed_discovery_artifacts: number
  remaining_discovery_artifacts: number
  insights: number
  challenged: number
  published: number
  domains: number
  mechanisms: number
  latest_run: PipelineRun | null
  events: Array<{ id: string; event_type: string; message: string; details: Record<string, unknown>; created_at: string }>
}

export interface AtlasGraph {
  nodes: Array<{ id: string; kind: string; label: string; artifact_id?: string; status?: string; confidence?: number }>
  edges: Array<{ id: string; source: string; target: string; relation: string }>
  insights: number
}

export function getAtlasOverview(conference = "CVPR", year = 2026) {
  const params = new URLSearchParams({ conference, year: String(year) })
  return api<AtlasOverview>(`/api/atlas/overview?${params}`)
}

export function getAtlasInsights(conference = "CVPR", year = 2026) {
  const params = new URLSearchParams({ conference, year: String(year) })
  return api<{ items: MethodInsight[]; total: number }>(`/api/atlas/insights?${params}`)
}

export function getAtlasGraph(conference = "CVPR", year = 2026) {
  const params = new URLSearchParams({ conference, year: String(year) })
  return api<AtlasGraph>(`/api/atlas/graph?${params}`)
}

export function startAtlasSynthesis(payload: {
  conference: string
  year: number
  max_rounds: number
  artifacts_per_round: number
  max_input_chars: number
}) {
  return api<{ status: string; run_id: string; message: string }>("/api/atlas/synthesis/start", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function stopAtlasSynthesis(runId: string) {
  return api<{ status: string; message: string }>(`/api/atlas/synthesis/${runId}/stop`, { method: "POST" })
}

export function updateMethodInsightStatus(insightId: string, status: string) {
  return api<{ id: string; status: string }>(`/api/atlas/insights/${insightId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  })
}

export interface ModelProviderConfig {
  id: string
  name: string
  provider: string
  base_url: string
  model_name: string
  is_default: boolean
  status: string
  has_api_key: boolean
  api_key_mask: string | null
  created_at: string
  updated_at: string
}

export interface ModelProviderConfigInput {
  name: string
  provider: string
  base_url: string
  model_name: string
  api_key?: string
  is_default: boolean
}

export function getModelConfigs() {
  return api<{ items: ModelProviderConfig[]; total: number }>("/api/model-configs")
}

export function createModelConfig(payload: ModelProviderConfigInput) {
  return api<ModelProviderConfig>("/api/model-configs", { method: "POST", body: JSON.stringify(payload) })
}

export function updateModelConfig(id: string, payload: ModelProviderConfigInput) {
  return api<ModelProviderConfig>(`/api/model-configs/${id}`, { method: "PUT", body: JSON.stringify(payload) })
}
