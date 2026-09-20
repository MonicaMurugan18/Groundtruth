"""Guardrail engine: runtime safety and policy enforcement.

Two layers, run in order:

1. **Deterministic policies** (``app.guardrails.policies``) - always active, no
   network, no API key. These guarantee that the guardrail verdict reflects real
   checks on every request rather than a decorative label.
2. **Guardrails AI validators** - loaded when installed. They are optional
   (``pip install guardrails-ai-detect-pii`` / ``guardrails-ai-toxic-language``),
   so the engine reports exactly which ones are active and never claims a check
   ran when it did not. A validator that raises is reported once and then
   quarantined, so a broken check cannot silently pass *or* flag everything.

The verdict is the most severe finding across both layers. Input is checked
before retrieval so an unsafe query never reaches the corpus or the LLM; output
is checked before the answer is returned.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.config.settings import get_settings
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

# Hub validators to attempt, as (module path, class name, severity, kwargs).
# Any that are not installed are skipped and reported as inactive.
#
# Install with pip, not the `guardrails hub` CLI: that CLI and its private
# registry are deprecated, and validators now ship on PyPI as
# `guardrails-ai-<name>`.
#
# DetectPII is deliberately scoped. Its default preset (`pii_entities="pii"`)
# includes DATE_TIME, LOCATION and PERSON, so it flags "Refunds are available
# within 7 days" as PII (DATE_TIME, score 0.85). A validator that fires on
# essentially every answer tells an operator nothing, so this narrows it to
# entities that genuinely constitute a privacy disclosure in an agent response.
#
# ToxicLanguage builds a Detoxify model when constructed, downloading several
# hundred MB of weights on a cold cache. That is paid at start-up (warm-up
# calls active_validators), so it is skippable via settings - see
# `toxic_language_enabled` and the guard in _load_hub_validators below.
_HUB_VALIDATORS: tuple[tuple[str, str, Severity, dict], ...] = (
    ("guardrails.hub", "ToxicLanguage", Severity.BLOCK, {}),
    (
        "guardrails.hub",
        "DetectPII",
        Severity.REVIEW,
        {
            "pii_entities": [
                "EMAIL_ADDRESS",
                "PHONE_NUMBER",
                "CREDIT_CARD",
                "US_SSN",
                "US_PASSPORT",
                "IBAN_CODE",
                "IP_ADDRESS",
            ]
        },
    ),
)


@dataclass(slots=True)
class _LoadedValidator:
    name: str
    validator: object
    severity: Severity
    # The Guard wrapping this validator, built once at load time. Constructing a
    # Guard per validation measured 520ms against 39ms for a reused one — a 13x
    # penalty that, across two validators on both input and output, added about
    # two seconds to every request.
    guard: object | None = None


class GuardrailEngine:
    """Applies input and output guardrails and returns a structured verdict."""

    def __init__(self) -> None:
        self._hub_validators: list[_LoadedValidator] | None = None
        # Hub validators quarantined after raising; see _run_hub_validators.
        self._broken: set[str] = set()

    # -- Guardrails AI hub -------------------------------------------------

    def _load_hub_validators(self) -> list[_LoadedValidator]:
        """Import whichever hub validators are actually installed."""
        if self._hub_validators is not None:
            return self._hub_validators

        # Note on log noise: Guardrails AI registers an anonymous OTLP span
        # exporter at `import guardrails`. On a network that cannot resolve its
        # endpoint, its background thread logs a ConnectionError traceback per
        # export. Neither `settings.disable_tracing` nor
        # `settings.rc.enable_metrics` suppresses it (both were measured: 6
        # tracebacks either way) because the exporter is already registered
        # before either can be set. The only effective opt-out is machine-level:
        #     guardrails configure --disable-metrics
        # It is cosmetic — validation results are unaffected — so it is left to
        # the operator rather than worked around in code.

        settings = get_settings()

        loaded: list[_LoadedValidator] = []
        for module_path, class_name, severity, kwargs in _HUB_VALIDATORS:
            # Checked before the import, not just before construction: the
            # point is that a disabled validator must not pull its model at
            # all. A skipped validator is simply absent from
            # `active_validators`, so the capabilities view keeps telling the
            # truth about which checks actually ran.
            if class_name == "ToxicLanguage" and not settings.toxic_language_enabled:
                logger.info(
                    "Guardrails hub validator ToxicLanguage is disabled by "
                    "configuration (APP_ENV=%s, DISABLE_TOXIC_LANGUAGE=%s); "
                    "skipping its model download.",
                    settings.app_env,
                    settings.disable_toxic_language,
                )
                continue
            try:
                module = __import__(module_path, fromlist=[class_name])
                validator_cls = getattr(module, class_name)
            except (ImportError, AttributeError):
                logger.info(
                    "Guardrails hub validator %s is not installed; skipping. "
                    "Install with: pip install guardrails-ai-%s",
                    class_name,
                    _snake(class_name).replace("_", "-"),
                )
                continue
            try:
                from guardrails import Guard

                validator = validator_cls(on_fail="noop", **kwargs)
                loaded.append(
                    _LoadedValidator(
                        name=class_name,
                        validator=validator,
                        severity=severity,
                        guard=Guard().use(validator),
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
            if entry.name in self._broken:
                continue  # already quarantined; see below
            try:
                if entry.guard is None:  # pragma: no cover - defensive
                    from guardrails import Guard

                    entry.guard = Guard().use(entry.validator)  # type: ignore[arg-type]
                outcome = entry.guard.validate(text)  # type: ignore[attr-defined]
            except Exception as exc:
                # A validator that errors must not be silently treated as a
                # pass, so the first failure is surfaced as REVIEW.
                #
                # But it must not flag every request either. A permanently
                # broken validator (a missing NLTK corpus, say) would otherwise
                # push every single answer to NEEDS_REVIEW, which destroys the
                # signal entirely — observed with ToxicLanguage before its
                # punkt_tab data was present. So after reporting once, the
                # validator is quarantined for the life of the process and its
                # absence is reported through `active_validators`.
                logger.error(
                    "Guardrails validator %s errored and has been disabled for this "
                    "process; fix the cause and restart: %s",
                    entry.name,
                    exc,
                )
                self._broken.add(entry.name)
                findings.append(
                    Finding(
                        validator=f"{entry.name} (error)",
                        severity=Severity.REVIEW,
                        message=(
                            f"Guardrails AI validator {entry.name} could not run "
                            f"({type(exc).__name__}), so its check is unverified. It "
                            "has been disabled until the service restarts."
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
            # There is nothing to validate in empty text, and hub validators do
            # not all handle it sensibly: DetectPII returns validation_passed
            # False for an empty string, which flagged every blocked or failed
            # answer (they have no answer text) as a PII disclosure.
            # `run_policies` already short-circuits on empty input; match it.
            if text and text.strip():
                # Hub validators are synchronous and can be slow; keep the
                # event loop free.
                findings.extend(await asyncio.to_thread(self._run_hub_validators, text))
            return _verdict(findings, stage)

        if trace is not None:
            with trace.span(GUARDRAIL):
                return await _run()
        return await _run()

    def active_validators(self) -> list[str]:
        """Names of every check that actually runs, for the capabilities view."""
        deterministic = [policy.name for policy in (*INPUT_POLICIES, *OUTPUT_POLICIES)]
        hub = [
            entry.name
            for entry in self._load_hub_validators()
            if entry.name not in self._broken
        ]
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
