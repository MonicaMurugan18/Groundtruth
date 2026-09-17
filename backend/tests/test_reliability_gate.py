"""Reliability gate tests.

These cover the decision logic itself, with metric values supplied directly, so
they run with no API key and no network. That separation is deliberate: the gate
is the component that decides whether a user sees an answer, so its behaviour
must be pinned by tests that cannot be affected by LLM variance.

Covers hackathon test cases 1-3 at the gate level; the end-to-end versions that
exercise real RAGAS scoring live in ``test_evaluation_cases.py``.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.evaluation.reliability import decide
from app.schemas.common import (
    ContextValidationStatus,
    GuardrailStatus,
    MetricStatus,
    ReliabilityStatus,
)
from app.schemas.evaluation import (
    ContextValidation,
    FactualVerification,
    GuardrailResult,
    MetricScore,
)

SETTINGS = Settings(
    faithfulness_threshold=0.70,
    relevance_threshold=0.70,
    context_precision_threshold=0.50,
)


def _ok(value: float) -> MetricScore:
    return MetricScore(value=value, status=MetricStatus.OK)


def _context(status: ContextValidationStatus = ContextValidationStatus.RELEVANT):
    return ContextValidation(
        status=status, reason="test fixture", chunks_retrieved=1, max_similarity=0.8
    )


def _guardrail(status: GuardrailStatus = GuardrailStatus.PASS):
    return GuardrailResult(status=status, reason="test fixture")


def _factual(status: MetricStatus = MetricStatus.NOT_APPLICABLE, correct: bool | None = None):
    return FactualVerification(status=status, correct=correct, reason="test fixture")


def _decide(**overrides):
    kwargs = {
        "faithfulness": _ok(0.95),
        "relevance": _ok(0.92),
        "context_precision": _ok(0.88),
        "context": _context(),
        "guardrail": _guardrail(),
        "factual": _factual(),
        "answer": "Refunds are available within 7 days.",
        "settings": SETTINGS,
    }
    kwargs.update(overrides)
    return decide(**kwargs)


# --- Test 1: supported answer ------------------------------------------------


def test_supported_answer_is_reliable():
    """High scores across the board yield RELIABLE."""
    verdict = _decide()
    assert verdict.status is ReliabilityStatus.RELIABLE
    assert verdict.supported is True


def test_reliable_explanation_does_not_claim_factual_truth():
    """A pass must not be presented as proof the answer is factually correct."""
    verdict = _decide()
    assert "not independent factual truth" in verdict.explanation


# --- Test 2: unsupported answer ---------------------------------------------


def test_unsupported_answer_fails():
    """Faithfulness below threshold is a hard failure, not a warning."""
    verdict = _decide(faithfulness=_ok(0.20))
    assert verdict.status is ReliabilityStatus.FAILED
    assert verdict.supported is False
    assert "not supported by the retrieved context" in verdict.explanation


def test_faithfulness_exactly_at_threshold_passes():
    """The threshold is inclusive, so a boundary score must not flip the verdict."""
    verdict = _decide(faithfulness=_ok(0.70))
    assert verdict.supported is True
    assert verdict.status is ReliabilityStatus.RELIABLE


# --- Test 3: irrelevant context ---------------------------------------------


def test_irrelevant_context_fails_as_retrieval_fault():
    """Irrelevant context fails, and the explanation blames retrieval."""
    verdict = _decide(context=_context(ContextValidationStatus.IRRELEVANT))
    assert verdict.status is ReliabilityStatus.FAILED
    assert "retrieved context does not address the question" in verdict.explanation


def test_empty_context_fails_and_points_at_ingestion():
    verdict = _decide(context=_context(ContextValidationStatus.EMPTY))
    assert verdict.status is ReliabilityStatus.FAILED
    assert "ingested" in verdict.explanation


def test_insufficient_context_needs_review():
    """Partially relevant context degrades rather than failing outright."""
    verdict = _decide(context=_context(ContextValidationStatus.INSUFFICIENT))
    assert verdict.status is ReliabilityStatus.NEEDS_REVIEW


# --- Test 4: guardrails -----------------------------------------------------


def test_guardrail_block_overrides_perfect_scores():
    """A safety block is terminal regardless of how good the scores are."""
    verdict = _decide(
        guardrail=GuardrailResult(
            status=GuardrailStatus.BLOCK, reason="Unsafe action detected."
        )
    )
    assert verdict.status is ReliabilityStatus.FAILED
    assert "Blocked by the safety layer" in verdict.explanation


def test_guardrail_review_downgrades_to_needs_review():
    verdict = _decide(
        guardrail=GuardrailResult(status=GuardrailStatus.REVIEW, reason="PII detected.")
    )
    assert verdict.status is ReliabilityStatus.NEEDS_REVIEW


# --- Faithfulness vs factuality ---------------------------------------------


def test_faithful_but_factually_wrong_answer_fails():
    """The core distinction: perfect grounding does not survive a factual conflict.

    This is the case RAGAS alone cannot catch - the answer faithfully repeats a
    context that happens to be wrong.
    """
    verdict = _decide(
        faithfulness=_ok(1.0),
        factual=FactualVerification(
            status=MetricStatus.OK,
            correct=False,
            score=0.0,
            reason="The reference says 7 days; the answer says 30 days.",
        ),
    )
    assert verdict.status is ReliabilityStatus.FAILED
    assert "contradicts the supplied reference answer" in verdict.explanation


def test_missing_reference_does_not_penalise_the_answer():
    """NOT_APPLICABLE factual status must not count against a grounded answer."""
    verdict = _decide(factual=_factual(MetricStatus.NOT_APPLICABLE))
    assert verdict.status is ReliabilityStatus.RELIABLE


# --- Unavailable metrics ----------------------------------------------------


def test_unavailable_faithfulness_does_not_pass_by_default():
    """A metric that could not be computed must not be treated as a pass."""
    verdict = _decide(
        faithfulness=MetricScore(status=MetricStatus.UNAVAILABLE, detail="no API key")
    )
    assert verdict.status is ReliabilityStatus.NEEDS_REVIEW
    assert verdict.supported is None
    assert any("Faithfulness could not be computed" in w for w in verdict.warnings)


def test_unavailable_metric_is_not_scored_as_zero():
    """UNAVAILABLE must not be reported as a failing score of 0."""
    verdict = _decide(
        faithfulness=MetricScore(status=MetricStatus.UNAVAILABLE, detail="no API key")
    )
    # A zero score would have produced FAILED; unavailable produces NEEDS_REVIEW.
    assert verdict.status is not ReliabilityStatus.FAILED


def test_empty_answer_fails():
    verdict = _decide(answer="   ")
    assert verdict.status is ReliabilityStatus.FAILED


# --- Relevance --------------------------------------------------------------


def test_low_relevance_needs_review():
    """A grounded but off-topic answer is flagged, not failed."""
    verdict = _decide(relevance=_ok(0.30))
    assert verdict.status is ReliabilityStatus.NEEDS_REVIEW
    assert "drifts from what was actually asked" in verdict.explanation


@pytest.mark.parametrize("score", [0.0, 0.49])
def test_low_context_precision_needs_review(score: float):
    verdict = _decide(context_precision=_ok(score))
    assert verdict.status is ReliabilityStatus.NEEDS_REVIEW
