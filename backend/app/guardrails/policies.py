"""Deterministic safety and policy validators.

These run on every request regardless of whether Guardrails AI hub validators
are installed, so the guardrail column is never a decorative "safe" label. Each
validator is a pure function over text that returns a finding or ``None``.

Deterministic checks are used for the categories where pattern matching is
genuinely reliable - credential leakage, contact-detail exfiltration, explicit
requests for weapon or malware synthesis, and prompt-injection markers. Nuanced
judgement is left to the Guardrails AI layer in ``engine.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    """How the pipeline should react when a validator fires."""

    BLOCK = "block"
    REVIEW = "review"


@dataclass(slots=True)
class Finding:
    validator: str
    severity: Severity
    message: str
    excerpt: str | None = None


@dataclass(slots=True)
class Policy:
    """A named pattern-based rule."""

    name: str
    severity: Severity
    message: str
    patterns: tuple[re.Pattern[str], ...]

    def check(self, text: str) -> Finding | None:
        for pattern in self.patterns:
            match = pattern.search(text)
            if match:
                return Finding(
                    validator=self.name,
                    severity=self.severity,
                    message=self.message,
                    excerpt=_redact(match.group(0)),
                )
        return None


def _compile(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


def _redact(value: str, keep: int = 4) -> str:
    """Show only enough of a match to be recognisable in the trace."""
    value = value.strip()
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * min(len(value) - keep, 12)


# --------------------------------------------------------------------------
# Input policies - applied to the user's query before retrieval
# --------------------------------------------------------------------------

INPUT_POLICIES: tuple[Policy, ...] = (
    Policy(
        name="weapons_or_explosives",
        severity=Severity.BLOCK,
        message="Request seeks instructions for building weapons or explosives.",
        patterns=_compile(
            r"\bhow\s+(?:to|do\s+i)\s+(?:make|build|construct|synthesi[sz]e)\b[^.?!]{0,60}\b"
            r"(?:bomb|explosive|ied|napalm|nerve\s+agent|sarin|ricin)\b",
            r"\b(?:build|make|construct)\s+a\s+(?:pipe\s+)?bomb\b",
        ),
    ),
    Policy(
        name="malware_generation",
        severity=Severity.BLOCK,
        message="Request seeks malicious software or an intrusion technique.",
        patterns=_compile(
            r"\b(?:write|create|generate|build)\b[^.?!]{0,40}\b"
            r"(?:ransomware|keylogger|rootkit|botnet|trojan|computer\s+virus)\b",
            r"\bhow\s+(?:to|do\s+i)\s+hack\s+(?:into\s+)?(?:someone|a\s+person|their|his|her)\b",
        ),
    ),
    Policy(
        name="self_harm",
        severity=Severity.BLOCK,
        message="Request relates to self-harm and should be routed to a human and crisis resources.",
        patterns=_compile(
            r"\bhow\s+(?:to|do\s+i)\s+(?:kill\s+myself|commit\s+suicide|end\s+my\s+life)\b",
            r"\b(?:most\s+)?(?:painless|effective|quickest)\s+way\s+to\s+(?:die|kill\s+myself)\b",
        ),
    ),
    Policy(
        name="prompt_injection",
        severity=Severity.REVIEW,
        message=(
            "Query contains instruction-override phrasing typical of a prompt-injection "
            "attempt. The agent must treat it as data, not as instructions."
        ),
        patterns=_compile(
            r"\bignore\s+(?:all\s+)?(?:your\s+|the\s+)?(?:previous|prior|above)\s+instructions?\b",
            r"\bdisregard\s+(?:all\s+)?(?:your\s+|the\s+)?(?:previous|prior)\s+(?:instructions?|rules?)\b",
            r"\byou\s+are\s+now\s+(?:in\s+)?(?:developer|admin|god|dan)\s+mode\b",
            r"\breveal\s+your\s+(?:system\s+)?(?:prompt|instructions)\b",
        ),
    ),
    Policy(
        name="credential_request",
        severity=Severity.BLOCK,
        message="Request asks the agent to disclose secrets or credentials.",
        patterns=_compile(
            r"\b(?:what\s+is|show\s+me|print|reveal|give\s+me)\b[^.?!]{0,30}\b"
            r"(?:api[_\s-]?key|secret[_\s-]?key|password|access[_\s-]?token|private[_\s-]?key)\b",
        ),
    ),
)


# --------------------------------------------------------------------------
# Output policies - applied to the generated answer before it reaches the user
# --------------------------------------------------------------------------

OUTPUT_POLICIES: tuple[Policy, ...] = (
    Policy(
        name="credential_leak",
        severity=Severity.BLOCK,
        message="Answer appears to contain a live API key or access token.",
        patterns=_compile(
            r"\bsk-[A-Za-z0-9]{20,}\b",           # OpenAI-style secret key
            r"\bghp_[A-Za-z0-9]{30,}\b",          # GitHub personal access token
            r"\bAKIA[0-9A-Z]{16}\b",              # AWS access key id
            r"\bAIza[0-9A-Za-z_-]{30,}\b",        # Google API key
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-----",
        ),
    ),
    Policy(
        name="pii_disclosure",
        severity=Severity.REVIEW,
        message="Answer contains what looks like personal contact or identity data.",
        patterns=_compile(
            r"\b\d{3}-\d{2}-\d{4}\b",                                  # US SSN
            r"\b(?:\d[ -]?){13,16}\b(?=\s*(?:$|[.,;]))",               # card-like number
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",     # email address
        ),
    ),
    Policy(
        name="unsupported_claim_language",
        severity=Severity.REVIEW,
        message=(
            "Answer asserts certainty or guarantees that a retrieval-grounded agent "
            "cannot justify from context alone."
        ),
        patterns=_compile(
            r"\b(?:i\s+)?guarantee(?:d|s)?\s+(?:that\s+)?(?:you|this|it)\b",
            r"\b100%\s+(?:certain|guaranteed|accurate|safe)\b",
            r"\bthere\s+is\s+no\s+(?:risk|chance|possibility)\s+(?:of|that)\b",
        ),
    ),
)


def run_policies(text: str, policies: tuple[Policy, ...]) -> list[Finding]:
    """Run every policy and collect all findings (not just the first)."""
    if not text or not text.strip():
        return []
    findings = [finding for policy in policies if (finding := policy.check(text))]
    # Blocking findings first so the caller's verdict logic sees the worst case.
    findings.sort(key=lambda f: 0 if f.severity is Severity.BLOCK else 1)
    return findings
