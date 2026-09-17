"""Groundtruth LiveKit voice agent.

Routes spoken interactions through the same evaluation pipeline as typed ones.

    user speaks -> LiveKit STT -> consult_groundtruth() -> POST /query
                                                             |
              retrieval -> context validation -> guardrails -> RAGAS -> trace
                                                             |
                     spoken answer  <-  evaluated answer  <--+
                                                             |
                     live trust report on the data channel  <+

Design note: the agent deliberately does **not** do its own retrieval or answer
generation. It delegates both to the Groundtruth API, so a voice answer travels
exactly the same code path as a typed one and is scored by the same evaluator.
That is what makes the voice traces comparable with the text traces on the
dashboard, rather than a parallel implementation that might drift.

Speech models run on LiveKit Inference, so no separate STT/TTS provider key is
required beyond the LiveKit credentials themselves.

Run with:
    python agent.py dev        # development, hot reload
    python agent.py console    # terminal-only, no frontend needed
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
)
from livekit.plugins import silero

logger = logging.getLogger("groundtruth-agent")

AGENT_DIR = Path(__file__).resolve().parent
load_dotenv(AGENT_DIR / ".env")
load_dotenv(AGENT_DIR / ".env.local", override=True)

API_URL = os.getenv("GROUNDTRUTH_API_URL", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.getenv("GROUNDTRUTH_API_TOKEN", "")
TIMEOUT = float(os.getenv("GROUNDTRUTH_TIMEOUT", "45"))
AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "groundtruth-agent")

STT_MODEL = os.getenv("STT_MODEL", "deepgram/nova-3")
TTS_MODEL = os.getenv("TTS_MODEL", "cartesia/sonic-3")
TTS_VOICE = os.getenv("TTS_VOICE", "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc")

# The frontend's useDataChannel subscribes to this exact topic. Changing it
# silently breaks the live trust-report panel, so keep the two in sync.
EVAL_TOPIC = "groundtruth_eval"

INSTRUCTIONS = """\
You are the Groundtruth voice assistant. You answer questions about the
documents in the knowledge base, and every answer you give is independently
evaluated for reliability.

# How to answer

- For ANY question about the documents, you MUST call `consult_groundtruth`
  first. Never answer a content question from your own knowledge.
- Speak the answer it returns. Do not embellish it, do not add facts it did not
  contain, and do not soften a refusal.
- If it reports that the context does not cover the question, say so plainly.
  An honest "the documents do not cover that" is a good answer here.
- If it reports that the request was blocked for safety, briefly say you cannot
  help with that and move on.

# Output rules

You are speaking aloud, so:

- Plain conversational text only. No markdown, lists, JSON, or code.
- One to three sentences. Ask one question at a time.
- Do not read out scores, tool names, or internal details unless asked.
- Spell out numbers and dates naturally.
"""


class GroundtruthAssistant(Agent):
    """Voice agent whose answers come from the Groundtruth evaluation pipeline."""

    def __init__(self, *, room=None) -> None:
        super().__init__(
            # Runs on LiveKit Inference; no provider API key required.
            llm=inference.LLM(model="openai/gpt-5.2-chat-latest"),
            instructions=INSTRUCTIONS,
        )
        self._room = room
        headers = {"Content-Type": "application/json"}
        if API_TOKEN:
            headers["Authorization"] = f"Bearer {API_TOKEN}"
        self._http = httpx.AsyncClient(base_url=API_URL, headers=headers, timeout=TIMEOUT)

    async def _publish_evaluation(self, payload: dict) -> None:
        """Push the trust report to the browser so it renders live."""
        if self._room is None:
            return
        try:
            await self._room.local_participant.publish_data(
                payload=json.dumps(payload, default=str).encode("utf-8"),
                reliable=True,
                topic=EVAL_TOPIC,
            )
        except Exception:
            # The panel is a nicety; failing to publish must not break the call.
            logger.exception("Failed to publish evaluation to the data channel")

    @function_tool()
    async def consult_groundtruth(self, context: RunContext, query: str) -> str:
        """Answer a question using the evaluated knowledge base.

        Call this for every question about the documents. It retrieves context,
        generates a grounded answer, applies safety guardrails and scores the
        result for reliability.

        Args:
            query: The user's question, transcribed as faithfully as possible.
        """
        try:
            response = await self._http.post(
                "/query", json={"query": query, "channel": "voice"}
            )
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Groundtruth returned %s", exc.response.status_code)
            return (
                "I could not reach the evaluation service just now, so I do not "
                "have a verified answer for that."
            )
        except Exception:
            logger.exception("Groundtruth request failed")
            return (
                "I could not reach the evaluation service just now, so I do not "
                "have a verified answer for that."
            )

        await self._publish_evaluation(result)

        status = result.get("status")
        answer = (result.get("answer") or "").strip()
        guardrail = (result.get("guardrail") or {}).get("status")

        if guardrail == "block":
            reason = (result.get("guardrail") or {}).get("reason", "")
            logger.info("Turn blocked by guardrail: %s", reason)
            return (
                "That request was blocked by the safety layer, so I cannot help "
                "with it."
            )

        if not answer:
            return "I do not have an answer for that from the documents I have."

        # Surface the reliability verdict to the LLM so its spoken framing can
        # match how much the answer should be trusted.
        if status == "failed":
            return (
                f"{answer}\n\n(Reliability check FAILED for this answer. Tell the "
                "user plainly that you could not verify it against the documents.)"
            )
        if status == "needs_review":
            return (
                f"{answer}\n\n(Reliability check flagged this for review. Mention "
                "briefly that you are not fully certain.)"
            )
        return answer


server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def groundtruth_agent(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        stt=inference.STT(model=STT_MODEL, language="multi"),
        tts=inference.TTS(model=TTS_MODEL, voice=TTS_VOICE),
        # inference.TurnDetector replaces the deprecated
        # livekit.plugins.turn_detector plugin as of livekit-agents 1.8.
        turn_detection=inference.TurnDetector(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    await session.start(
        agent=GroundtruthAssistant(room=ctx.room),
        room=ctx.room,
    )
    await ctx.connect()

    await session.generate_reply(
        instructions=(
            "Greet the user in one short sentence, introduce yourself as the "
            "Groundtruth assistant, and invite them to ask a question about the "
            "documents in the knowledge base."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)
