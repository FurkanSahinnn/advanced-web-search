"""
Central configuration for Advanced Web Search.

Everything is optional. With no environment variables and no API keys,
Advanced Web Search runs against keyless web/academic sources and a local Ollama model
(if Ollama is installed). Adding a cloud API key automatically upgrades the
default models — see `llm/provider.py` for routing.

Settings precedence (low -> high):
    built-in defaults  ->  .env / environment  ->  persisted app_settings (DB)

The DB-persisted overrides are applied at runtime by the settings service;
this module only owns process/env-level configuration and sane defaults.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from dotenv import load_dotenv

    # Load .env into the PROCESS environment so os.getenv(...) (provider-key
    # detection here + in the source connectors) AND litellm (which reads
    # os.environ for ANTHROPIC_API_KEY etc.) actually see keys placed in .env.
    # pydantic-settings only maps .env into Settings fields, NOT into os.environ.
    load_dotenv()  # nearest .env (current working dir / parents)
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)  # repo-root .env
except Exception:  # pragma: no cover - dotenv always present via pydantic-settings
    pass

# Agent roles that can each be assigned their own model.
AgentRole = Literal["planner", "moderator", "synthesizer", "verifier"]
AGENT_ROLES: tuple[AgentRole, ...] = ("planner", "moderator", "synthesizer", "verifier")

# ---------------------------------------------------------------------------
# Local model tiers, keyed by approximate available system RAM (GB).
# Used by llm/hardware.py to recommend a default local model the user's
# machine can actually run. The user can always override in Settings.
# Model ids are Ollama tags (provider prefix added by the LLM layer).
# ---------------------------------------------------------------------------
LOCAL_MODEL_TIERS: list[dict] = [
    {"min_ram_gb": 0, "model": "qwen3:1.7b", "label": "Tiny (<8 GB RAM)"},
    {"min_ram_gb": 8, "model": "qwen3:4b", "label": "Small (8-16 GB RAM)"},
    {"min_ram_gb": 16, "model": "qwen3:8b", "label": "Balanced (16-32 GB RAM)"},
    {"min_ram_gb": 32, "model": "qwen3:14b", "label": "Large (32-64 GB RAM)"},
    {"min_ram_gb": 64, "model": "qwen3:30b", "label": "X-Large (64 GB+ RAM)"},
]

# Cloud "cheap + great" defaults, chosen per provider when a key is present.
# Strings are litellm model identifiers.
CLOUD_DEFAULTS: dict[str, str] = {
    "anthropic": "anthropic/claude-haiku-4-5",
    "openai": "openai/gpt-4o-mini",
    "gemini": "gemini/gemini-2.5-flash",
    "groq": "groq/llama-3.3-70b-versatile",
    "deepseek": "deepseek/deepseek-chat",
    "openrouter": "openrouter/anthropic/claude-haiku-4.5",
}

# Stronger sibling per provider, used by llm.provider.escalate() to re-verify a
# CONTESTED claim with a more capable model when a cloud key is present ("Small
# LMs Need Strong Verifiers", 2404.17140). A provider whose default is already
# its strongest cheap option maps to itself (escalation is then a no-op).
CLOUD_STRONG: dict[str, str] = {
    "anthropic": "anthropic/claude-sonnet-4-5",
    "openai": "openai/gpt-4o",
    "gemini": "gemini/gemini-2.5-pro",
    "groq": "groq/llama-3.3-70b-versatile",
    "deepseek": "deepseek/deepseek-reasoner",
    "openrouter": "openrouter/anthropic/claude-sonnet-4.5",
}

# Default multi-signal source-ranking weights (must sum to ~1.0).
DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "relevance": 0.40,
    "authority": 0.15,
    "recency": 0.15,
    "citation_impact": 0.15,
    "evidence": 0.15,
}

# ---------------------------------------------------------------------------
# Search-depth presets. A single user choice ("how comprehensive?") drives the
# breadth knobs AND the deeper-search behaviours:
#   max_research_rounds  -> iterative gap-driven follow-up search rounds
#   snowball / snowball_top_k -> citation snowballing (refs + citing works)
#   bilingual            -> TR<->EN query expansion per sub-question
#   recursion_depth      -> how many levels the gap loop may add sub-questions
# ---------------------------------------------------------------------------
# NOTE on report_max_tokens: this caps the synthesizer's streamed report length.
# 8000 is chosen to stay within the *output* limit of EVERY default cloud
# provider so a long report is never rejected with a 400 — DeepSeek's 8192 is
# the lowest cap among them (Claude Haiku 4.5 allows far more). The old
# hard-coded 4000 truncated long reports mid-section.
# Two deeper-quality knobs ride along on the preset (the project's "one user
# choice drives everything" convention):
#   self_refine  -> run a reflect-then-revise (Self-Refine) critic pass over the
#                   synthesized report before claim extraction. Off for the fast
#                   presets (extra LLM calls); on for deep/exhaustive.
#   entail_votes -> how many independent samples the verifier draws per
#                   (claim, passage) entailment judgement, taking the majority
#                   verdict (self-consistency). 1 = today's single-sample path.
#   crag         -> Corrective-RAG sufficiency gate in the gap node: grade each
#                   sub-question by the ranker's ABSOLUTE rerank confidence
#                   (Correct/Ambiguous/Incorrect) instead of a raw kept-source
#                   COUNT, trigger a targeted follow-up only on the weak ones,
#                   and early-exit the gap loop when every sub-question is already
#                   well-covered (don't burn the round budget). Falls back to the
#                   count proxy when the reranker is degraded. Off for quick.
#   outline_revision -> let the gap node revise the OUTLINE from what was actually
#                   retrieved: a one-shot (round 1) pass that proposes new angles
#                   the sources reveal but the planner missed (additive, deduped,
#                   capped). Biased additive to avoid oscillation. Deep+ only.
#   contextual_retrieval -> Anthropic-style Contextual Retrieval at ingest: prepend
#                   a 1-sentence situating blurb (one batched local-LLM call per
#                   source group, metadata fallback) to each chunk BEFORE embedding
#                   + FTS indexing, so a chunk that lost its document context still
#                   matches. Raw chunk is kept separately for display. Deep+ only.
#   verifier_escalation -> when an entailment verdict comes back CONTESTED
#                   (unsupported/partial), re-check that claim ONCE with a stronger
#                   model (next Ollama tier, RAM-clamped, or the provider's strong
#                   cloud sibling) and adopt the verdict only if MORE supportive —
#                   rescuing small-model false negatives. Deep+ only.
DEPTH_PRESETS: dict[str, dict] = {
    "quick": {
        "max_subtopics": 4, "results_per_source": 6, "max_sources_per_subtopic": 12,
        "max_research_rounds": 1, "snowball": False, "snowball_top_k": 0,
        "bilingual": False, "recursion_depth": 1, "report_max_tokens": 4000,
        "self_refine": False, "entail_votes": 1, "query_variants": 1, "crag": False,
        "outline_revision": False, "contextual_retrieval": False,
        "verifier_escalation": False,
    },
    "standard": {
        "max_subtopics": 8, "results_per_source": 8, "max_sources_per_subtopic": 20,
        "max_research_rounds": 2, "snowball": False, "snowball_top_k": 0,
        "bilingual": True, "recursion_depth": 1, "report_max_tokens": 6000,
        "self_refine": False, "entail_votes": 1, "query_variants": 3, "crag": True,
        "outline_revision": False, "contextual_retrieval": False,
        "verifier_escalation": False,
    },
    "deep": {
        "max_subtopics": 12, "results_per_source": 10, "max_sources_per_subtopic": 30,
        "max_research_rounds": 3, "snowball": True, "snowball_top_k": 8,
        "bilingual": True, "recursion_depth": 2, "report_max_tokens": 8000,
        "self_refine": True, "entail_votes": 3, "query_variants": 3, "crag": True,
        "outline_revision": True, "contextual_retrieval": True,
        "verifier_escalation": True,
    },
    "exhaustive": {
        "max_subtopics": 18, "results_per_source": 12, "max_sources_per_subtopic": 45,
        "max_research_rounds": 4, "snowball": True, "snowball_top_k": 15,
        "bilingual": True, "recursion_depth": 2, "report_max_tokens": 8000,
        "self_refine": True, "entail_votes": 3, "query_variants": 3, "crag": True,
        "outline_revision": True, "contextual_retrieval": True,
        "verifier_escalation": True,
    },
}
DEFAULT_DEPTH = "quick"


def depth_preset(name: str | None) -> dict:
    """Return a copy of a depth preset (falls back to the default)."""
    return dict(DEPTH_PRESETS.get(name or DEFAULT_DEPTH, DEPTH_PRESETS[DEFAULT_DEPTH]))


# ---------------------------------------------------------------------------
# Report OUTPUT languages.
#
# The synthesizer renders the final report in one or MORE of these languages.
# Each requested language is produced by its OWN parallel LLM request, so a
# multi-language run never has to squeeze every language into a single response
# (which would hit the model's output/context limit).
#
# IMPORTANT: this dict is only the MENU the UI offers. A run ONLY ever generates
# the languages the user explicitly selected — by default a single,
# auto-detected language. We never fan out to "all" languages.
#
# Codes are mapped to an English name used to instruct the LLM ("Write the
# report in Turkish"); an English name is more reliable than a bare code.
# ---------------------------------------------------------------------------
REPORT_LANGUAGE_NAMES: dict[str, str] = {
    "tr": "Turkish",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ar": "Arabic",
    "ru": "Russian",
    "zh": "Chinese (Simplified)",
}
SUPPORTED_REPORT_LANGUAGES: tuple[str, ...] = tuple(REPORT_LANGUAGE_NAMES.keys())
DEFAULT_REPORT_LANGUAGE = "en"  # fallback when auto-detection is inconclusive
MAX_REPORT_LANGUAGES = 5        # bound the synthesizer's parallel fan-out per run


def language_name(code: str | None) -> str:
    """Human-readable English name for a language code (for LLM instructions)."""
    if not code:
        return ""
    return REPORT_LANGUAGE_NAMES.get(code.lower().strip(), code)


def sanitize_report_languages(values) -> list[str]:
    """Clean raw report-language input into an ordered, deduped, capped list.

    Keeps the special ``"auto"`` token plus any supported language code
    (lowercased); drops unknowns; dedups preserving order; caps the count at
    ``MAX_REPORT_LANGUAGES``. Returns ``["auto"]`` when nothing usable remains so
    a run always has at least one language to render. The ``"auto"`` token is
    resolved to a concrete language at synthesis time (it needs the query text).
    """
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    seen: set[str] = set()
    for v in values or []:
        code = str(v or "").lower().strip()
        if not code or code in seen:
            continue
        if code == "auto" or code in REPORT_LANGUAGE_NAMES:
            out.append(code)
            seen.add(code)
        if len(out) >= MAX_REPORT_LANGUAGES:
            break
    return out or ["auto"]


class Settings(BaseSettings):
    """Process/environment-level settings (12-factor friendly)."""

    model_config = SettingsConfigDict(
        env_prefix="AWSEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- server ---
    host: str = "127.0.0.1"
    port: int = 8787
    log_level: str = "info"

    # --- storage ---
    data_dir: Path = Field(default=Path("./data"))

    # --- local inference ---
    use_local_llm: bool = True  # when False: never probe/fall back to Ollama (cloud-only)
    ollama_base_url: str = "http://localhost:11434"
    local_model: str | None = None  # explicit override; else auto-picked by RAM

    # --- embeddings / reranking (ONNX via fastembed by default) ---
    # 1024-dim multilingual (TR/EN), fastembed-supported. bge-m3 was dropped by
    # newer fastembed; the embedder also falls back to a supported model if the
    # configured one can't load, so vector search never silently turns off.
    embed_model: str = "intfloat/multilingual-e5-large"
    embed_dim: int = 1024
    # Multilingual cross-encoder (TR/EN). The previous default "Xenova/bge-reranker-base"
    # is not in fastembed's registry, so it silently fell back to this same model — set it
    # explicitly to drop the failed-load attempt (and confusing log) at startup.
    rerank_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    use_torch_models: bool = False  # opt-in to sentence-transformers/torch path

    # --- retrieval ---
    rrf_k: int = 60
    rerank_top_k: int = 50
    keep_threshold: float = 0.45  # final_score below this is dropped

    # --- research run limits ---
    max_subtopics: int = 12
    results_per_source: int = 8
    max_sources_per_subtopic: int = 25
    verifier_max_iterations: int = 2
    require_approval: bool = True  # HITL gate before expensive retrieval

    # --- comprehensiveness / deep-search ---
    depth: str = DEFAULT_DEPTH            # quick | standard | deep | exhaustive
    max_research_rounds: int = 3          # iterative gap-driven follow-up rounds (cap)
    gap_min_sources: int = 3             # a sub-question with fewer kept sources is "under-covered"
    query_variants: int = 3              # bilingual/paraphrase query variants per sub-question
    snowball_top_k: int = 8              # # of top academic sources to snowball from

    # --- optional provider keys / contact (mirrors .env.example) ---
    contact_email: str | None = None
    searxng_url: str | None = None

    # ----- derived paths -----
    @property
    def data_path(self) -> Path:
        p = self.data_dir.expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        # Filename intentionally kept as the legacy "lumina.db" so existing
        # local databases survive the project rename without an explicit
        # migration. It is an internal data file, never shown in the UI.
        return self.data_path / "lumina.db"

    @property
    def model_cache_path(self) -> Path:
        p = self.data_path / "models_cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def http_cache_path(self) -> Path:
        p = self.data_path / "http_cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ----- provider key detection (read from raw env, not prefixed) -----
    @property
    def available_cloud_providers(self) -> list[str]:
        """Cloud providers with a key present, in preference order."""
        order = [
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
            ("gemini", "GEMINI_API_KEY"),
            ("groq", "GROQ_API_KEY"),
            ("deepseek", "DEEPSEEK_API_KEY"),
            ("openrouter", "OPENROUTER_API_KEY"),
        ]
        return [name for name, env in order if os.getenv(env)]

    @property
    def has_tavily(self) -> bool:
        return bool(os.getenv("TAVILY_API_KEY"))

    @property
    def has_core(self) -> bool:
        return bool(os.getenv("CORE_API_KEY"))

    @property
    def has_brave(self) -> bool:
        return bool(os.getenv("BRAVE_API_KEY"))

    @property
    def has_openalex_key(self) -> bool:
        return bool(os.getenv("OPENALEX_API_KEY"))

    @property
    def has_semantic_scholar_key(self) -> bool:
        return bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
