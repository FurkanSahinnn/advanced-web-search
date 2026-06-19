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
    verified: bool = False
    dead_link: bool = False


class ReportOut(BaseModel):
    id: int
    run_id: int
    markdown: str
    language: str = "en"
    ord: int = 0
    consensus_summary: Optional[str] = None
    comprehensiveness: Optional[float] = None
    certainty: Optional[float] = None
    created_at: str


class RunOut(BaseModel):
    id: int
    project_id: int
    thread_id: str
    status: str
    error: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None


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


class LLMStatus(BaseModel):
    mode: Literal["cloud", "local", "none"]
    active_provider: Optional[str] = None
    effective_models: ModelMap
    cloud_providers: list[str] = Field(default_factory=list)
    ollama_available: bool = False
    ollama_models: list[str] = Field(default_factory=list)


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


# --------------------------------------------------------------------------- #
# Streaming events (SSE)
# --------------------------------------------------------------------------- #

EventType = Literal[
    "run_started", "status", "node_started", "node_finished",
    "plan", "subtopic", "awaiting_approval",
    "source_found", "source_scored", "claim", "citation_verified",
    "token", "report", "run_finished", "error", "log",
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
