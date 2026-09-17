"""Shared enumerations used across the evaluation pipeline."""

from __future__ import annotations

from enum import Enum


class ReliabilityStatus(str, Enum):
    """The overall verdict Groundtruth returns for an interaction."""

    RELIABLE = "reliable"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class GuardrailStatus(str, Enum):
    """Outcome of the safety/policy layer."""

    PASS = "pass"
    REVIEW = "review"
    BLOCK = "block"


class ContextValidationStatus(str, Enum):
    """Whether retrieval actually produced usable grounding for the query."""

    RELEVANT = "relevant"
    INSUFFICIENT = "insufficient"
    IRRELEVANT = "irrelevant"
    EMPTY = "empty"


class MetricStatus(str, Enum):
    """Why a metric does or does not carry a value.

    ``UNAVAILABLE`` is deliberately distinct from a score of 0.0: a metric that
    could not be computed (no LLM judge configured, evaluator error) must never
    be presented as a bad score, and must never be invented.
    """

    OK = "ok"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"


class SourceChannel(str, Enum):
    """How the interaction reached Groundtruth."""

    TEXT = "text"
    VOICE = "voice"


class RetrievalBackend(str, Enum):
    """Which retrieval engine produced the context."""

    MOSS = "moss"
    FAISS = "faiss"
    NONE = "none"
