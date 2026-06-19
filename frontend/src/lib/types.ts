// TS mirrors of backend/advanced_web_search/models/schemas.py DTOs.

export type EvidenceType =
  | "meta_analysis"
  | "systematic_review"
  | "rct"
  | "peer_reviewed"
  | "preprint"
  | "dataset"
  | "reputable_news"
  | "blog"
  | "unknown";

export interface ScoreWeights {
  relevance: number;
  authority: number;
  recency: number;
  citation_impact: number;
  evidence: number;
}

export interface ScoreBreakdown {
  relevance: number;
  authority: number;
  recency: number;
  citation_impact: number;
  evidence: number;
  final_score: number;
  match_score: number;
  evidence_type: EvidenceType;
  kept: boolean;
  why_kept: string;
  supporting_quote: string;
  detail: Record<string, unknown>;
}

export interface SubtopicOut {
  id: number;
  parent_id: number | null;
  question: string;
  perspective: string | null;
  rationale: string | null;
  depth: number;
  ord: number;
  approved: boolean;
  status: string;
  children: SubtopicOut[];
}

export interface ProjectOut {
  id: number;
  title: string;
  root_query: string;
  language: string;
  report_languages: string[];
  status: string;
  created_at: string;
  updated_at: string;
}

export interface SourceOut {
  id: number;
  subtopic_id: number | null;
  canonical_id: string;
  kind: string; // web | academic | preprint | ...
  provider: string | null;
  title: string | null;
  authors: string[];
  venue: string | null;
  published_date: string | null;
  url: string | null;
  pdf_url: string | null;
  abstract: string | null;
  cited_by_count: number | null;
  is_oa: boolean;
  score: ScoreBreakdown | null;
}

export interface CitationOut {
  id: number;
  source_id: number;
  stance: string; // supporting | refuting | neutral
  supporting_quote: string | null;
  verified: boolean;
  dead_link: boolean;
}

export interface ClaimOut {
  id: number;
  subtopic_id: number | null;
  text: string;
  status: string; // supported | disputed | ...
  citations: CitationOut[];
}

export interface ReportOut {
  id: number;
  run_id: number;
  markdown: string;
  language: string;
  ord?: number;
  consensus_summary: string | null;
  comprehensiveness: number | null;
  certainty: number | null;
  created_at: string;
}

export interface RunOut {
  id: number;
  project_id: number;
  thread_id: string;
  status: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

// ----- Settings / hardware / LLM status -----

export interface ModelMap {
  planner: string | null;
  moderator: string | null;
  synthesizer: string | null;
  verifier: string | null;
}

export interface LocalModelOption {
  model: string;
  label: string;
  min_ram_gb: number;
  fits: boolean;
}

export interface HardwareInfo {
  total_ram_gb: number;
  available_ram_gb: number;
  cpu_count: number;
  recommended_local_model: string;
  options: LocalModelOption[];
}

export type ProviderKind = "cloud" | "local" | "web" | "academic";

export interface ProviderStatus {
  name: string;
  kind: ProviderKind;
  available: boolean;
  requires_key: boolean;
  note: string | null;
}

export type LLMMode = "cloud" | "local" | "none";

export interface LLMStatus {
  mode: LLMMode;
  active_provider: string | null;
  effective_models: ModelMap;
  cloud_providers: string[];
  ollama_available: boolean;
  ollama_models: string[];
}

export type SearchDepth = "quick" | "standard" | "deep" | "exhaustive";

export type ExportFormat = "bibtex" | "ris" | "csl" | "markdown" | "html";

export interface DepthPreset {
  max_subtopics: number;
  results_per_source: number;
  max_sources_per_subtopic: number;
  max_research_rounds: number;
  snowball: boolean;
  snowball_top_k: number;
  bilingual: boolean;
  recursion_depth: number;
}

export interface SettingsOut {
  model_map: ModelMap;
  weights: ScoreWeights;
  require_approval: boolean;
  use_local_llm: boolean;
  keep_threshold: number;
  max_subtopics: number;
  results_per_source: number;
  depth: string;
  max_research_rounds: number;
  gap_min_sources: number;
  query_variants: number;
  snowball_top_k: number;
  depth_presets: Record<string, DepthPreset>;
  hardware: HardwareInfo;
  llm: LLMStatus;
  providers: ProviderStatus[];
}

export interface TestLLMResult {
  ok: boolean;
  provider: string | null;
  model: string | null;
  latency_ms: number;
  sample: string;
  error: string | null;
}

export interface SettingsUpdate {
  model_map?: Partial<ModelMap>;
  weights?: ScoreWeights;
  require_approval?: boolean;
  use_local_llm?: boolean;
  keep_threshold?: number;
  max_subtopics?: number;
  results_per_source?: number;
  depth?: string;
  max_research_rounds?: number;
  gap_min_sources?: number;
  query_variants?: number;
  snowball_top_k?: number;
}

// ----- Request bodies -----

export interface ProjectCreate {
  query: string;
  title?: string;
  language?: string;
  report_languages?: string[];
  weights?: ScoreWeights;
  require_approval?: boolean;
  depth?: SearchDepth;
}

export interface SubtopicEdit {
  id: number; // < 0 => newly added
  parent_id: number | null;
  question: string;
  perspective: string | null;
  keep: boolean;
}

export interface ApprovalDecision {
  approved_subtopics: SubtopicEdit[];
  extra_instructions?: string;
}

// ----- SSE events -----

export type EventType =
  | "run_started"
  | "status"
  | "node_started"
  | "node_finished"
  | "plan"
  | "subtopic"
  | "awaiting_approval"
  | "source_found"
  | "source_scored"
  | "claim"
  | "citation_verified"
  | "token"
  | "report"
  | "run_finished"
  | "error"
  | "log";

export type NodeName =
  | "planner"
  | "moderator"
  | "approval"
  | "researcher"
  | "ranker"
  | "synthesizer"
  | "verifier"
  | "finalizer";

export interface ResearchEvent {
  type: EventType;
  run_id: number;
  seq: number;
  node?: string | null;
  message?: string | null;
  data: Record<string, any>;
}

// Detailed project response from GET /api/projects/{id}
export interface ProjectDetail {
  project: ProjectOut;
  latest_run: RunOut | null;
  subtopics: SubtopicOut[];
  report: ReportOut | null;
  reports: ReportOut[];
  sources: SourceOut[];
  claims: ClaimOut[];
}

export interface CreateProjectResponse {
  project: ProjectOut;
  run: RunOut;
}

export interface HealthResponse {
  status: string;
  version: string;
}
