"""Guardrail engine: runtime safety and policy enforcement.

Two layers, run in order:

1. **Deterministic policies** (``app.guardrails.policies``) - always active, no
   network, no API key. These guarantee that the guardrail verdict reflects real
   checks on every request rather than a decorative label.
2. **Guardrails AI validators** - loaded from the installed Guardrails hub when
   present. Hub validators are an optional install (``guardrails hub install``),
   so the engine reports exactly which ones are active and never claims a check
   ran when it did not.

The verdict is the most severe finding across both layers. Input is checked
before retrieval so an unsafe query never reaches the corpus or the LLM; output
is checked before the answer is returned.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.guardrails.policies import (
    INPUT_POLICIES,
    OUTPUT_POLICIES,
    Finding,
    Severity,
    run_policies,
)
from app.schemas.common import GuardrailStatus
from app.schemas.evaluation import GuardrailResult
from app.tracing.timer import GUARDRAIL, LatencyTrace

logger = logging.getLogger(__name__)

# Hub validators to attempt, as (module path, class name, severity).
# Any that are not installed are skipped and reported as inactive.
_HUB_VALIDATORS: tuple[tuple[str, str, Severity], ...] = (
    ("guardrails.hub", "ToxicLanguage", Severity.BLOCK),
    ("guardrails.hub", "DetectPII", Severity.REVIEW),
)


@dataclass(slots=True)
class _LoadedValidator:
    name: str
    validator: object
    severity: Severity


class GuardrailEngine:
    """Applies input and output guardrails and returns a structured verdict."""

    def __init__(self) -> None:
        self._hub_validators: list[_LoadedValidator] | None = None

    # -- Guardrails AI hub -------------------------------------------------

    def _load_hub_validators(self) -> list[_LoadedValidator]:
        """Import whichever hub validators are actually installed."""
        if self._hub_validators is not None:
            return self._hub_validators

        loaded: list[_LoadedValidator] = []
        for module_path, class_name, severity in _HUB_VALIDATORS:
            try:
                module = __import__(module_path, fromlist=[class_name])
                validator_cls = getattr(module, class_name)
            except (ImportError, AttributeError):
                logger.info(
                    "Guardrails hub validator %s is not installed; skipping. "
                    "Install with: guardrails hub install hub://guardrails/%s",
                    class_name,
                    _snake(class_name),
                )
                continue
            try:
                loaded.append(
                    _LoadedValidator(
                        name=class_name,
                        validator=validator_cls(on_fail="noop"),
                        severity=severity,
                    )
                )
                logger.info("Guardrails AI validator %s active", class_name)
            except Exception:
                logger.exception("Guardrails validator %s failed to initialise", class_name)

        self._hub_validators = loaded
        return loaded

    def _run_hub_validators(self, text: str) -> list[Finding]:
        """Run installed hub validators, converting failures into findings."""
        findings: list[Finding] = []
        for entry in self._load_hub_validators():
            try:
                from guardrails import Guard

                guard = Guard().use(entry.validator)  # type: ignore[arg-type]
                outcome = guard.validate(text)
            except Exception as exc:
                # A validator that errors must not decide the verdict, and must
                # not be silently treated as a pass.
                logger.warning("Guardrails validator %s errored: %s", entry.name, exc)
                findings.append(
                    Finding(
                        validator=f"{entry.name} (error)",
                        severity=Severity.REVIEW,
                        message=(
                            f"Guardrails AI validator {entry.name} could not run "
                            f"({type(exc).__name__}), so its check is unverified."
                        ),
                    )
                )
                continue

            if not getattr(outcome, "validation_passed", True):
                findings.append(
                    Finding(
                        validator=entry.name,
                        severity=entry.severity,
                        message=f"Guardrails AI validator {entry.name} failed.",
                    )
                )
        return findings

    # -- Public API --------------------------------------------------------

    async def check_input(
        self, query: str, *, trace: LatencyTrace | None = None
    ) -> GuardrailResult:
        """Validate the user's query before it reaches retrieval or the LLM."""
        return await self._check(query, INPUT_POLICIES, stage="input", trace=trace)

    async def check_output(
        self, answer: str, *, trace: LatencyTrace | None = None
    ) -> GuardrailResult:
        """Validate the generated answer before it is returned."""
        return await self._check(answer, OUTPUT_POLICIES, stage="output", trace=trace)

    async def _check(
        self,
        text: str,
        policies: tuple,
        *,
        stage: str,
        trace: LatencyTrace | None,
    ) -> GuardrailResult:
        async def _run() -> GuardrailResult:
            findings = run_policies(text, policies)
            # Hub validators are synchronous and can be slow; keep the event
            # loop free.
            findings.extend(await asyncio.to_thread(self._run_hub_validators, text))
            return _verdict(findings, stage)

        if trace is not None:
            with trace.span(GUARDRAIL):
                return await _run()
        return await _run()

    def active_validators(self) -> list[str]:
        """Names of every check that actually runs, for the capabilities view."""
        deterministic = [policy.name for policy in (*INPUT_POLICIES, *OUTPUT_POLICIES)]
        hub = [entry.name for entry in self._load_hub_validators()]
        return deterministic + hub


def _verdict(findings: list[Finding], stage: str) -> GuardrailResult:
    """Reduce findings to a single status, worst severity wins."""
    if not findings:
        return GuardrailResult(
            status=GuardrailStatus.PASS,
            reason="No safety or policy violation detected.",
            triggered=[],
            stage=stage,
        )

    blocking = [f for f in findings if f.severity is Severity.BLOCK]
    chosen = blocking or findings
    status = GuardrailStatus.BLOCK if blocking else GuardrailStatus.REVIEW

    reason = " ".join(
        f"{finding.message}"
        + (f" (matched: {finding.excerpt})" if finding.excerpt else "")
        for finding in chosen
    )
    return GuardrailResult(
        status=status,
        reason=reason.strip(),
        triggered=[finding.validator for finding in findings],
        stage=stage,
    )


def _snake(name: str) -> str:
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index:
            out.append("_")
        out.append(char.lower())
    return "".join(out)


_engine: GuardrailEngine | None = None


def get_guardrail_engine() -> GuardrailEngine:
    global _engine
    if _engine is None:
        _engine = GuardrailEngine()
    return _engine
