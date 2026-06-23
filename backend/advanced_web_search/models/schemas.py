"""
Pydantic DTOs shared across the API, the graph, and the persistence layer.

Naming convention:
  * `*Create` / `*Update`  -> request bodies
  * `*Out`                 -> response bodies (serialized DB rows)
  * plain names            -> internal value objects passed through the graph
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

EvidenceType = Literal[
    "meta_analysis", "systematic_review", "rct", "peer_reviewed",
    "preprint", "dataset", "reputable_news", "blog", "unknown",
]


class ScoreWeights(BaseModel):
    relevance: float = 0.40
    authority: float = 0.15
    recency: float = 0.15
    citation_impact: float = 0.15
    evidence: float = 0.15

    def normalized(self) -> "ScoreWeights":
        total = (self.relevance + self.authority + self.recency
                 + self.citation_impact + self.evidence) or 1.0
        return ScoreWeights(
            relevance=self.relevance / total,
            authority=self.authority / total,
            recency=self.recency / total,
            citation_impact=self.citation_impact / total,
            evidence=self.evidence / total,
        )


class ScoreBreakdown(BaseModel):
    relevance: float = 0.0
    authority: float = 0.0
    recency: float = 0.0
    citation_impact: float = 0.0
    evidence: float = 0.0
    final_score: float = 0.0
    match_score: int = 0
    evidence_type: EvidenceType = "unknown"
    kept: bool = True
    why_kept: str = ""
    supporting_quote: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Projects / subtopics
# --------------------------------------------------------------------------- #

class ProjectCreate(BaseModel):
    query: str = Field(min_length=3, description="The root research question.")
    title: Optional[str] = None
    language: str = "auto"  # 'auto' | 'tr' | 'en' | ... (search hint)
    report_languages: Optional[list[str]] = None  # report output langs (menu: auto + supported)
    depth: Optional[str] = None  # quick | standard | deep | exhaustive
    weights: Optional[ScoreWeights] = None
    require_approval: Optional[bool] = None


class SubtopicOut(BaseModel):
    id: int
    parent_id: Optional[int] = None
    question: str
    perspective: Optional[str] = None
    rationale: Optional[str] = None
    depth: int = 0
    ord: int = 0
    approved: bool = False
    status: str = "pending"
    children: list["SubtopicOut"] = Field(default_factory=list)


class ProjectOut(BaseModel):
    id: int
    title: str
    root_query: str
    language: str
    report_languages: list[str] = Field(default_factory=list)
    status: str
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------- #
# Sources / scores / citations / report
# --------------------------------------------------------------------------- #

class SourceOut(BaseModel):
    id: int
    subtopic_id: Optional[int] = None
    canonical_id: str
    kind: str = "web"
    provider: Optional[str] = None
    title: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    venue: Optional[str] = None
    published_date: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    abstract: Optional[str] = None
    cited_by_count: Optional[int] = None
    is_oa: bool = False
    score: Optional[ScoreBreakdown] = None


class ClaimOut(BaseModel):
    id: int
    subtopic_id: Optional[int] = None
    text: str
    status: str = "supported"
    citations: list["CitationOut"] = Field(default_factory=list)


class CitationOut(BaseModel):
    id: int
    source_id: int
    stance: str = "supporting"
    supporting_quote: Optional[str] = None
    verified: bool = False          # link liveness (NOT entailment)
    dead_link: bool = False
    # Claim<->source entailment verdict: supported | partial | unsupported |
    # unverifiable. None when the citation has not been verified.
    support: Optional[str] = None
    support_score: Optional[float] = None


class ReportGrounding(BaseModel):
    """Post-verification entailment breakdown of the report's claims.

    Counts claims by their BEST citation verdict; `grounded` = supported|partial,
    `graded` = claims with any checked citation, `share` = grounded / graded
    (which the verifier also writes onto `certainty`).
    """
    supported: int = 0
    partial: int = 0
    unsupported: int = 0
    unverifiable: int = 0
    graded: int = 0
    grounded: int = 0
    share: float = 0.0


class ReportQuality(BaseModel):
    """Reference-free, post-verification quality scorecard for a run.

    A glanceable SELF-assessment (not a certification), mostly arithmetic over
    artifacts the run already produced:
      groundedness        share of claims their cited sources entail
      citation_precision  kept sources actually cited / kept sources
      citation_coverage   claims carrying >=1 citation / claims
      answer_relevance    cosine(report, root question)
      source_diversity    unique domains / kept sources
      reranker_degraded   the relevance ranking collapsed to source order
      embeddings_degraded answer_relevance couldn't be computed (no embedder)
      overall             mean of the 0-1 metrics (penalized if degraded)
    """
    groundedness: float = 0.0
    citation_precision: float = 0.0
    citation_coverage: float = 0.0
    answer_relevance: float = 0.0
    source_diversity: float = 0.0
    reranker_degraded: bool = False
    embeddings_degraded: bool = False
    overall: float = 0.0


class ReportOut(BaseModel):
    id: int
    run_id: int
    markdown: str
    language: str = "en"
    ord: int = 0
    consensus_summary: Optional[str] = None
    # Where the sources conflict / are uncertain — the counterpart to the
    # consensus summary. Empty/None when nothing notable was surfaced.
    disagreements: Optional[str] = None
    comprehensiveness: Optional[float] = None
    certainty: Optional[float] = None
    # Source ids in [n] citation order (index+1 == the inline [n] marker). Lets a
    # client resolve a citation marker to the exact source. Empty for older runs.
    references: list[int] = Field(default_factory=list)
    # Per-verdict claim-grounding breakdown, set after verification. None for
    # older runs / before the verifier has run.
    grounding: Optional[ReportGrounding] = None
    # Reference-free quality scorecard, set after verification. None for older
    # runs / before the verifier has run.
    quality: Optional[ReportQuality] = None
    created_at: str


class RunOut(BaseModel):
    id: int
    project_id: int
    thread_id: str
    status: str
    error: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None
    # Accumulated LLM accounting for the run (0 for older rows / local Ollama).
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0


class RunQueryOut(BaseModel):
    """One search query issued during the run (the research trail)."""
    id: int
    subtopic_id: Optional[int] = None
    round: int = 1
    query: str
    hits: int = 0
    created_at: Optional[str] = None


# --------------------------------------------------------------------------- #
# Ask-the-Report (grounded follow-up Q&A)
# --------------------------------------------------------------------------- #

class AskRequest(BaseModel):
    """A follow-up question answered ONLY from a run's gathered sources."""
    question: str = Field(min_length=2)
    language: Optional[str] = None  # answer language; auto-detected from the question if omitted


class AskAnswerOut(BaseModel):
    id: int
    question: str
    answer: str
    # Source ids cited in the answer, in [n] order (index+1 == the inline [n]).
    references: list[int] = Field(default_factory=list)
    # False when no relevant source text was found (the answer says so instead of
    # guessing) — the UI can flag the answer as ungrounded.
    grounded: bool = True
    created_at: Optional[str] = None


# --------------------------------------------------------------------------- #
# Human-in-the-loop approval
# --------------------------------------------------------------------------- #

class SubtopicEdit(BaseModel):
    """A node in the user-edited approval tree (id<0 means newly added)."""
    id: int
    parent_id: Optional[int] = None
    question: str
    perspective: Optional[str] = None
    keep: bool = True


class ApprovalDecision(BaseModel):
    approved_subtopics: list[SubtopicEdit]
    extra_instructions: Optional[str] = None


# --------------------------------------------------------------------------- #
# Settings / hardware / LLM status
# --------------------------------------------------------------------------- #

class ModelMap(BaseModel):
    """Per-agent model assignment. Values are litellm model identifiers."""
    planner: Optional[str] = None
    moderator: Optional[str] = None
    synthesizer: Optional[str] = None
    verifier: Optional[str] = None


class LocalModelOption(BaseModel):
    model: str
    label: str
    min_ram_gb: int
    fits: bool  # does the user's RAM comfortably fit this tier?


class HardwareInfo(BaseModel):
    total_ram_gb: float
    available_ram_gb: float
    cpu_count: int
    recommended_local_model: str
    options: list[LocalModelOption] = Field(default_factory=list)


class ProviderStatus(BaseModel):
    name: str
    kind: Literal["cloud", "local", "web", "academic"]
    available: bool
    requires_key: bool = False
    note: Optional[str] = None
    # Credential status for cloud providers (non-secret): whether a key is
    # stored, where it came from, and a last-4 hint when knowable.
    key_set: bool = False
    key_source: Optional[str] = None  # "vault" | "env"
    key_hint: Optional[str] = None


class LLMStatus(BaseModel):
    mode: Literal["cloud", "local", "none", "custom"]
    active_provider: Optional[str] = None
    effective_models: ModelMap
    cloud_providers: list[str] = Field(default_factory=list)
    ollama_available: bool = False
    ollama_models: list[str] = Field(default_factory=list)


class VaultStatus(BaseModel):
    """Non-secret status of the encrypted API-key vault."""
    configured: bool = False  # a master password has been set
    unlocked: bool = False    # the derived key is loaded in memory this process
    providers: list[str] = Field(default_factory=list)  # cloud names with a stored key


class ActiveLLM(BaseModel):
    """Which LLM backend the user pinned (``auto`` = cloud-if-key-else-local)."""
    kind: Literal["auto", "cloud", "ollama", "custom"] = "auto"
    provider: Optional[str] = None  # cloud provider name when kind == "cloud"


class CustomEndpoint(BaseModel):
    """A self-hosted OpenAI-compatible endpoint (LM Studio / vLLM / llama.cpp …)."""
    base_url: Optional[str] = None
    model: Optional[str] = None
    key_set: bool = False  # whether an (encrypted) endpoint key is stored


class SettingsOut(BaseModel):
    model_map: ModelMap
    weights: ScoreWeights
    require_approval: bool
    use_local_llm: bool = True
    keep_threshold: float
    max_subtopics: int
    results_per_source: int
    depth: str = "quick"
    max_research_rounds: int = 3
    gap_min_sources: int = 3
    query_variants: int = 3
    snowball_top_k: int = 8
    depth_presets: dict[str, Any] = Field(default_factory=dict)
    hardware: HardwareInfo
    llm: LLMStatus
    providers: list[ProviderStatus] = Field(default_factory=list)
    # LLM provider/endpoint configuration (UI-editable; keys via the vault).
    vault: VaultStatus = Field(default_factory=VaultStatus)
    active_llm: ActiveLLM = Field(default_factory=ActiveLLM)
    custom_endpoint: CustomEndpoint = Field(default_factory=CustomEndpoint)
    ollama_base_url: str = "http://localhost:11434"
    local_model: Optional[str] = None
    # provider -> default litellm model id, so the per-role picker can offer a
    # correctly-prefixed cloud option without duplicating CLOUD_DEFAULTS.
    cloud_defaults: dict[str, str] = Field(default_factory=dict)


class SettingsUpdate(BaseModel):
    model_map: Optional[ModelMap] = None
    weights: Optional[ScoreWeights] = None
    require_approval: Optional[bool] = None
    use_local_llm: Optional[bool] = None
    keep_threshold: Optional[float] = None
    max_subtopics: Optional[int] = None
    results_per_source: Optional[int] = None
    depth: Optional[str] = None
    max_research_rounds: Optional[int] = None
    gap_min_sources: Optional[int] = None
    query_variants: Optional[int] = None
    snowball_top_k: Optional[int] = None
    # LLM provider/endpoint config (non-secret; API keys go via /vault routes).
    active_llm: Optional[ActiveLLM] = None
    ollama_base_url: Optional[str] = None
    local_model: Optional[str] = None
    custom_base_url: Optional[str] = None
    custom_model: Optional[str] = None


# --------------------------------------------------------------------------- #
# Streaming events (SSE)
# --------------------------------------------------------------------------- #

EventType = Literal[
    "run_started", "status", "node_started", "node_finished",
    "plan", "subtopic", "awaiting_approval",
    "source_found", "source_scored", "query", "claim", "citation_verified",
    "token", "report", "report_grounding", "report_quality", "run_cost",
    "run_finished", "error", "log",
]


class ResearchEvent(BaseModel):
    """A single SSE frame streamed to the UI agent-trace view."""
    type: EventType
    run_id: int
    seq: int = 0
    node: Optional[str] = None
    message: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


SubtopicOut.model_rebuild()
ClaimOut.model_rebuild()
