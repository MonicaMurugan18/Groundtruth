"""CRISPE prompt registry.

Prompt templates live in ``app/prompts/templates/*.yaml`` rather than inline in
Python so they are reviewable, versioned, and changeable without touching
pipeline code. Each template carries a JSON Schema describing its structured
output; the evaluator validates model responses against it, so a malformed or
free-form reply is caught rather than silently parsed into a bogus score.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class PromptError(RuntimeError):
    """Raised when a template is missing, malformed, or rendered with bad args."""


@dataclass(slots=True)
class PromptTemplate:
    """A rendered-on-demand CRISPE prompt with a structured output contract."""

    id: str
    version: int
    description: str
    crispe: dict[str, str]
    rules: list[str]
    system_prompt: str
    user_prompt: str
    output_schema: dict[str, Any]

    def render_system(self) -> str:
        """Fill the system prompt from the CRISPE fields and rules.

        The declared JSON schema is appended verbatim. Describing the shape in
        prose is not enough for every model: asked "does the candidate convey
        the same facts?", gpt-oss-120b replied ``{"same_facts": false}`` - valid
        JSON, correct judgement, wrong contract. Showing the schema makes the
        templates portable across providers instead of relying on one model's
        ability to infer it.
        """
        fields = dict(self.crispe)
        fields["rules"] = "\n".join(f"- {rule}" for rule in self.rules)
        rendered = _safe_format(self.system_prompt, fields, self.id).strip()

        required = self.output_schema.get("required") or []
        schema_block = json.dumps(self.output_schema, indent=2)
        contract = (
            "Your reply must be a single JSON object matching this exact schema:\n"
            f"{schema_block}\n"
        )
        if required:
            contract += (
                "Every one of these keys is REQUIRED and must be present: "
                f"{', '.join(required)}. Use exactly these key names."
            )
        return f"{rendered}\n\n{contract}".strip()

    def render_user(self, **kwargs: Any) -> str:
        return _safe_format(self.user_prompt, kwargs, self.id).strip()

    def messages(self, **kwargs: Any) -> list[dict[str, str]]:
        """Chat messages ready to send to an OpenAI-compatible endpoint."""
        return [
            {"role": "system", "content": self.render_system()},
            {"role": "user", "content": self.render_user(**kwargs)},
        ]


def _safe_format(template: str, values: dict[str, Any], template_id: str) -> str:
    """Substitute ``{placeholder}`` tokens without tripping on JSON braces.

    ``str.format`` would choke on the literal braces that appear in prompts
    discussing JSON. This replaces only known keys and leaves everything else
    untouched.
    """
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return str(values[key])
        missing.append(key)
        return match.group(0)

    rendered = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, template)
    if missing:
        raise PromptError(
            f"Template {template_id!r} is missing values for: {', '.join(sorted(set(missing)))}"
        )
    return rendered


@lru_cache(maxsize=None)
def get_prompt(template_id: str) -> PromptTemplate:
    """Load and cache a template by id (its filename without extension)."""
    path = TEMPLATE_DIR / f"{template_id}.yaml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in TEMPLATE_DIR.glob("*.yaml")))
        raise PromptError(
            f"Prompt template {template_id!r} not found. Available: {available or 'none'}"
        )

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise PromptError(f"Prompt template {template_id!r} is not a YAML mapping.")

    required = ("system_prompt", "user_prompt", "output_schema")
    for field in required:
        if field not in data:
            raise PromptError(f"Prompt template {template_id!r} is missing {field!r}.")

    return PromptTemplate(
        id=str(data.get("id", template_id)),
        version=int(data.get("version", 1)),
        description=str(data.get("description", "")),
        crispe={str(k): str(v) for k, v in (data.get("crispe") or {}).items()},
        rules=[str(rule) for rule in (data.get("rules") or [])],
        system_prompt=str(data["system_prompt"]),
        user_prompt=str(data["user_prompt"]),
        output_schema=dict(data["output_schema"]),
    )


def list_prompts() -> list[str]:
    return sorted(path.stem for path in TEMPLATE_DIR.glob("*.yaml"))


def build_context_block(contexts: list[str]) -> str:
    """Render context passages as the numbered block every template expects.

    The numbering is load-bearing: templates ask the model to cite passages by
    index, and the citations are shown in the trace view.
    """
    if not contexts:
        return "(no context passages were retrieved)"
    return "\n\n".join(
        f"[{index}] {text.strip()}" for index, text in enumerate(contexts, start=1)
    )


def parse_json_response(raw: str, template_id: str) -> dict[str, Any]:
    """Parse a model reply into JSON, tolerating markdown fences.

    Raises :class:`PromptError` rather than returning a default, so a malformed
    evaluator response becomes a visible ERROR status instead of a fake score.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        # Last resort: the first balanced {...} span in the reply.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise PromptError(
                f"Template {template_id!r} returned non-JSON output: {raw[:200]!r}"
            ) from exc
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as inner:
            raise PromptError(
                f"Template {template_id!r} returned unparseable JSON: {raw[:200]!r}"
            ) from inner

    if not isinstance(parsed, dict):
        raise PromptError(f"Template {template_id!r} returned {type(parsed).__name__}, expected an object.")
    return parsed
