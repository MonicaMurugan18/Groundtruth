"""LLM access for generation and for the evaluation judge.

Two separate clients are exposed on purpose:

* :func:`get_generation_llm` - writes the agent's answer.
* :func:`get_judge_llm` - scores that answer. Pinned to temperature 0 so a
  re-run of the same triad yields the same verdict; a judge that drifts between
  runs cannot be used as a reliability gate.

If ``OPENAI_API_KEY`` is absent every call raises :class:`LLMNotConfigured`. The
pipeline catches that and marks the affected stage UNAVAILABLE rather than
emitting a placeholder score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.config.settings import Settings, get_settings
from app.prompts.registry import PromptTemplate, parse_json_response

logger = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    """Raised when an LLM call is attempted without an API key."""


class LLMCallFailed(RuntimeError):
    """Raised when the provider call fails or returns unusable output."""


@dataclass(slots=True)
class LLMReply:
    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def _client_kwargs(settings: Settings) -> dict[str, Any]:
    if not settings.llm_configured:
        raise LLMNotConfigured(
            "OPENAI_API_KEY is not set. Add it to backend/.env to enable answer "
            "generation and RAGAS evaluation."
        )
    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    # Optional override for any OpenAI-compatible gateway.
    if settings.openai_base_url.strip():
        kwargs["base_url"] = settings.openai_base_url.strip()
    return kwargs


def get_async_openai_client() -> Any:
    """Return a fresh AsyncOpenAI client.

    The configuration check runs *before* the import on purpose: importing
    ``openai`` costs several seconds on first use, and an unconfigured
    deployment should fail fast rather than pay that cost only to raise.
    """
    kwargs = _client_kwargs(get_settings())

    from openai import AsyncOpenAI

    return AsyncOpenAI(**kwargs)


async def complete(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float | None = None,
    json_mode: bool = False,
) -> LLMReply:
    """Send a chat completion request."""
    settings = get_settings()
    client = get_async_openai_client()
    chosen_model = model or settings.llm_model

    request: dict[str, Any] = {
        "model": chosen_model,
        "messages": messages,
        "temperature": settings.llm_temperature if temperature is None else temperature,
    }
    if json_mode:
        request["response_format"] = {"type": "json_object"}

    try:
        response = await client.chat.completions.create(**request)
    except Exception as exc:
        raise LLMCallFailed(f"LLM call failed ({chosen_model}): {exc}") from exc

    choice = response.choices[0] if response.choices else None
    content = (choice.message.content if choice and choice.message else None) or ""
    if not content.strip():
        raise LLMCallFailed(f"LLM returned an empty response ({chosen_model}).")

    usage = getattr(response, "usage", None)
    return LLMReply(
        text=content,
        model=chosen_model,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
    )


async def complete_structured(
    template: PromptTemplate,
    *,
    model: str | None = None,
    temperature: float | None = None,
    **template_args: Any,
) -> dict[str, Any]:
    """Run a CRISPE template and return its validated JSON object.

    Uses the provider's JSON mode and then validates the parsed object against
    the template's declared schema, so a structurally wrong reply raises instead
    of flowing into the scoring logic.
    """
    reply = await complete(
        template.messages(**template_args),
        model=model,
        temperature=temperature,
        json_mode=True,
    )
    payload = parse_json_response(reply.text, template.id)
    _validate_against_schema(payload, template.output_schema, template.id)
    return payload


def _validate_against_schema(
    payload: dict[str, Any], schema: dict[str, Any], template_id: str
) -> None:
    """Validate required keys and types declared by the template schema."""
    required = schema.get("required") or []
    missing = [key for key in required if key not in payload]
    if missing:
        raise LLMCallFailed(
            f"Template {template_id!r} response is missing required fields: "
            f"{', '.join(missing)}"
        )

    properties = schema.get("properties") or {}
    type_map: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "boolean": (bool,),
        "number": (int, float),
        "integer": (int,),
        "array": (list,),
        "object": (dict,),
    }
    for key, value in payload.items():
        declared = (properties.get(key) or {}).get("type")
        expected = type_map.get(declared) if declared else None
        if expected and not isinstance(value, expected):
            # bool is a subclass of int; reject it where a number is expected.
            if declared in {"number", "integer"} and isinstance(value, bool):
                raise LLMCallFailed(
                    f"Template {template_id!r} returned a boolean for numeric field {key!r}."
                )
            raise LLMCallFailed(
                f"Template {template_id!r} returned {type(value).__name__} for "
                f"field {key!r}, expected {declared}."
            )


# ---------------------------------------------------------------------------
# LangChain wrappers, required by RAGAS
# ---------------------------------------------------------------------------


def get_judge_llm() -> Any:
    """Return the deterministic LangChain LLM that RAGAS uses as its judge."""
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    if not settings.llm_configured:
        raise LLMNotConfigured(
            "OPENAI_API_KEY is not set, so RAGAS scoring cannot run. Groundtruth "
            "reports these metrics as unavailable rather than estimating them."
        )

    kwargs: dict[str, Any] = {
        "model": settings.eval_llm_model,
        "api_key": settings.openai_api_key,
        "temperature": 0.0,
    }
    if settings.openai_base_url.strip():
        kwargs["base_url"] = settings.openai_base_url.strip()
    return ChatOpenAI(**kwargs)


def get_judge_embeddings() -> Any:
    """Embeddings for RAGAS answer-relevance.

    Uses the same local Hugging Face model as retrieval, which keeps the metric
    free of API cost and consistent with how the corpus was indexed.
    """
    from langchain_community.embeddings import HuggingFaceEmbeddings

    settings = get_settings()
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        model_kwargs={"device": settings.embedding_device},
        encode_kwargs={"normalize_embeddings": True},
    )
