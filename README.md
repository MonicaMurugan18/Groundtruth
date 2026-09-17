# Groundtruth

**A reliability, safety and evaluation layer for RAG agents.**

Groundtruth wraps a retrieval-augmented agent and answers one question for every
interaction:

> Can we trust the information this agent just produced?

For each query it records the full RAG triad (query → retrieved context →
answer), scores the answer for faithfulness, relevance and retrieval quality,
applies runtime guardrails, measures real per-stage latency, and writes an
auditable trace to PostgreSQL. A Next.js dashboard makes each result
inspectable.

---

## The distinction this project is built around

RAGAS **faithfulness** measures whether an answer is supported by the context it
was given. It does **not** establish that the context is true.

An agent can faithfully repeat a stale policy document and be confidently wrong.
Groundtruth therefore treats these as two separate stages, end to end — separate
prompt templates, separate pipeline stages, separate database columns, separate
UI panels:

| Stage | Question it answers | When it runs |
|---|---|---|
| **Faithfulness** (RAGAS) | Is every claim in the answer entailed by the retrieved context? | Always |
| **Factual verification** | Is the answer actually correct? | Only when a reference answer is supplied |

With no reference answer, factual status is `NOT_APPLICABLE` and Groundtruth
makes **no** truth claim. Even a `RELIABLE` verdict states in words that it
measures grounding, "not independent factual truth."

### Two more honesty rules

- **An uncomputed metric is never a zero.** Scores are nullable with a companion
  status (`ok` / `unavailable` / `error` / `not_applicable`). The UI renders a
  hatched bar and "Not computed", never a red 0%. Missing metrics downgrade a
  verdict to `NEEDS_REVIEW` — they never pass by default.
- **Retrieval results are never misattributed.** If Moss is unconfigured or
  failing, retrieval falls back to FAISS, the trace is labelled
  `retrieval_backend: "faiss"`, and a warning says so. FAISS results are never
  presented as Moss results.

---

## Architecture

```
                         USER
                   text  |  voice
                         |
                 +-------v--------+
                 |    Next.js     |  dashboard + server-side API proxy
                 +-------+--------+
                         |  REST
                 +-------v--------+
                 |    FastAPI     |  orchestrator
                 +-------+--------+
                         |
    +--------------+-----+------+--------------+
    |              |            |              |
 Retrieval    Generation   Guardrails     Evaluation
    |              |            |              |
  Moss ──┐       LLM       policies +       RAGAS
         │                 Guardrails AI       |
       FAISS                                factuality
         |                                     |
    Relevant context ─────────────────────► verdict
                                               |
                                    latency + PostgreSQL
                                               |
                                        Next.js dashboard
```

Voice path (LiveKit):

```
user speaks → LiveKit room → voice agent → POST /query (channel=voice)
                                   ↓
        retrieval → context validation → guardrails → evaluation → trace
                                   ↓
        spoken answer + live trust report on the data channel
```

### Pipeline order, and why

1. **Input guardrail** — before retrieval, so an unsafe query never reaches the
   corpus or the LLM. A block short-circuits the whole pipeline.
2. **Retrieval** — Moss first, FAISS fallback, serving backend recorded.
3. **Context validation** — judges retrieval *before the answer exists*, so a
   retrieval failure is never misattributed to the generator.
4. **Generation** — grounded strictly in the retrieved passages.
5. **Output guardrail** — before the answer reaches the user.
6. **Evaluation** — RAGAS metrics, plus factual verification when applicable.
7. **Reliability gate** — deterministic; see below.
8. **Persistence** — full trace to PostgreSQL.

The gate is deliberately **not** an LLM call. Critical decisions run in
`app/evaluation/reliability.py`, in code that can be read, unit-tested and
argued with. The LLM's role ends at producing individual metrics.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind v4, Lucide |
| Voice | LiveKit (Agents + React components) |
| API | FastAPI, Pydantic v2, SQLAlchemy 2 (async), slowapi, PyJWT |
| Retrieval | **Moss** (primary), FAISS (fallback), Hugging Face embeddings |
| Evaluation | RAGAS 0.4, Guardrails AI, CRISPE prompt registry |
| Storage | PostgreSQL (traces), FAISS (vectors) |
| LLM | OpenAI (generation + evaluation judge) |

---

## Prerequisites

- **Python 3.11** — required. `guardrails-ai` caps at `<3.14`, and `faiss-cpu`
  ships Windows wheels for 3.11. Python 3.14 will not work.
- **Node.js 20+**
- **Docker** (for PostgreSQL) — optional; a SQLite fallback is supported.

---

## Setup

### 1. Environment

```bash
cp .env.example backend/.env
```

Then edit `backend/.env`. `backend/.env` is gitignored and must never be
committed.

Generate a JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2. Database

```bash
docker compose up -d postgres
```

To run without Docker, set this in `backend/.env` instead:

```
DATABASE_URL=sqlite+aiosqlite:///./data/groundtruth.db
```

The schema is created automatically at startup.

### 3. Backend

```bash
cd backend
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

API docs: <http://127.0.0.1:8000/docs>

On startup the server warms the embedding model and guardrail imports in the
background (~20 s). It accepts connections immediately; the first query is fast
once warm-up logs `Warm-up complete`.

### 4. Frontend

```bash
cd frontend
cp .env.example .env.local   # optional; defaults work for local development
npm install
npm run dev
```

Dashboard: <http://localhost:3000>

`frontend/.env.local` holds no secrets of its own — only where the backend lives
and, once auth is enabled, the API token the server-side proxy attaches. Nothing
there is prefixed `NEXT_PUBLIC_`, so nothing reaches the browser.

### 5. Voice agent (optional)

```bash
cd agent
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe agent.py dev
```

---

## Environment variables

All of these live in `backend/.env`. Only `OPENAI_API_KEY` is required for full
functionality; everything else degrades visibly rather than silently.

### Required for real evaluation

| Variable | Purpose | Where to get it |
|---|---|---|
| `OPENAI_API_KEY` | RAG generation + RAGAS judge | <https://platform.openai.com/api-keys> |

Without it the pipeline still runs — retrieval, guardrails, context validation
and latency all work — but generation and RAGAS scoring report as
`unavailable` rather than producing invented numbers.

### Moss (primary retrieval)

| Variable | Default | Notes |
|---|---|---|
| `MOSS_PROJECT_ID` | — | From the Moss dashboard |
| `MOSS_PROJECT_KEY` | — | From the Moss dashboard |
| `MOSS_INDEX_NAME` | `groundtruth-knowledge` | |
| `MOSS_MODEL_ID` | `moss-minilm` | |
| `MOSS_TOP_K` / `MOSS_ALPHA` | `5` / `0.8` | `alpha` is hybrid-search weighting |
| `RETRIEVAL_BACKEND` | `moss` | `moss` or `faiss` |

Variable names were taken from the official
[`livekit-examples/moss-hacker-starter`](https://github.com/livekit-examples/moss-hacker-starter),
not invented. Moss docs: <https://docs.usemoss.dev/>

### LiveKit (voice)

| Variable | Notes |
|---|---|
| `LIVEKIT_URL` | `wss://<project>.livekit.cloud` |
| `LIVEKIT_API_KEY` | From LiveKit Cloud, or `lk app env` |
| `LIVEKIT_API_SECRET` | Server-side only — never sent to the browser |
| `LIVEKIT_AGENT_NAME` | Default `groundtruth-agent` |

### Other

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | Postgres | Trace store |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Local, no API key |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `800` / `120` | |
| `FAITHFULNESS_THRESHOLD` | `0.70` | Reliability gate |
| `RELEVANCE_THRESHOLD` | `0.70` | Reliability gate |
| `CONTEXT_PRECISION_THRESHOLD` | `0.50` | Reliability gate |
| `AUTH_DISABLED` | `true` | Must be `false` in production |
| `RATE_LIMIT_PER_MINUTE` | `30` | |
| `CORS_ORIGINS` | `http://localhost:3000` | Explicit allowlist |

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /query` | Full pipeline: retrieve → generate → evaluate |
| `POST /evaluate` | Score a Query/Context/Answer triad you supply |
| `POST /ingest` | Upload `.txt`, `.md` or `.pdf` |
| `POST /ingest/text` | Ingest inline text |
| `GET /ingest/documents` | List the corpus |
| `GET /traces` | Paginated history |
| `GET /traces/{id}` | One full trace |
| `GET /stats` | Dashboard aggregates |
| `GET /voice/token` | Mint a LiveKit token |
| `POST /voice/turn` | Evaluate one spoken turn |
| `GET /health/capabilities` | Which integrations are actually configured |

`/health/capabilities` is the honesty endpoint — it reports exactly what is and
is not wired up, so a low score can be distinguished from a missing credential.

---

## Testing

```bash
cd backend
.venv/Scripts/python.exe -m pytest          # offline tests, no API key needed
.venv/Scripts/python.exe -m pytest -m live  # real RAGAS scoring, needs OPENAI_API_KEY
```

The offline suite (67 tests) covers the components whose behaviour must not
depend on LLM variance:

- **Reliability gate** — every verdict path, including that an *uncomputed*
  metric downgrades to `NEEDS_REVIEW` rather than passing or being scored zero.
- **Guardrail policies** — unsafe inputs blocked, benign support questions
  allowed through, and matched secrets redacted rather than echoed.
- **Latency tracer** — measured against real elapsed sleeps, so a hardcoded
  duration would fail. Includes the repeated-stage accumulation the guardrail
  depends on.
- **Trace persistence** — round-trip fidelity, and that `AVG` skips NULL scores
  instead of averaging them as zero.
- **Security** — the production configuration guard, JWT expiry/forgery/issuer
  rejection, and upload path-traversal sanitisation.

Context validation has two modes. With an LLM judge it distinguishes "on-topic
but missing the specific detail" from "genuinely relevant". Without one it falls
back to embedding similarity alone, which still separates the clear cases — a
leave-policy passage scores 0.17 against a refund question versus 0.60 for the
refund passage — and the trace says which mode produced the verdict. Cases 3 and
4 therefore pass end-to-end even with no API key configured.

The `live` suite covers the project's reliability cases against a real judge:

| Case | Setup | Expected |
|---|---|---|
| 1. Supported answer | Context "7 days", answer "7 days" | High faithfulness |
| 2. Unsupported answer | Context "7 days", answer "30 days" | Low faithfulness, `FAILED` |
| 3. Irrelevant context | Refund question, leave-policy context | Context validation failure |
| 4. Unsafe request | Weapons query | Guardrail `BLOCK` before retrieval |
| 5. Latency | Any query | Real per-stage timings |
| Faithful ≠ factual | Grounded answer, contradicting reference | High faithfulness, `FAILED` on factuality |

---

## Guardrails

Two layers:

1. **Deterministic policies** (`app/guardrails/policies.py`) — always active, no
   API key, no network. Input: weapons, malware, self-harm, prompt injection,
   credential requests. Output: leaked API keys, PII, overconfident claims.
   Matched secrets are redacted in the trace, never echoed.
2. **Guardrails AI hub validators** — used when installed. They are an optional
   install, so the engine reports which are actually active and never claims a
   check ran when it did not:

```bash
guardrails hub install hub://guardrails/toxic_language
guardrails hub install hub://guardrails/detect_pii
```

A validator that errors produces a `REVIEW`, never a silent pass.

---

## Security

- Secrets only in `backend/.env` (gitignored); `.env.example` holds placeholders.
- The browser never sees an API token — the Next.js route handler at
  `/api/gt/[...path]` proxies server-side and attaches credentials there.
- The LiveKit API secret never leaves the backend; the browser gets a
  short-lived, room-scoped JWT with narrow grants (audio only, one room).
- Pydantic validation on every endpoint; uploads are extension- and
  size-limited, and filenames are sanitised against path traversal.
- Rate limiting via slowapi; CORS is an explicit allowlist, never `*`.
- In production (`APP_ENV=production`) the API **refuses to start** with auth
  disabled, a default JWT secret, or wildcard CORS.

---

## Known limitations

- **RAGAS costs LLM calls.** Each evaluation runs three metrics, each making
  judge calls. Expect a few seconds and a few cents per evaluation.
- **Faithfulness is not factuality.** Stated throughout, and the reason factual
  verification is a separate, opt-in stage.
- **LLM-as-judge has variance.** Scores near a threshold can flip between runs.
  The judge is pinned to temperature 0 to reduce this, and the live tests assert
  relative ordering where absolute calibration would be fragile.
- **Guardrail policies are pattern-based.** They catch clear-cut cases with high
  precision; they are not a complete safety solution. Nuanced judgement is left
  to the Guardrails AI layer.
- **First request after startup is slower** if warm-up has not finished.
- **Auth is scaffolded, not enforced by default.** `AUTH_DISABLED=true` in dev;
  the JWT path is implemented and OAuth2 can replace `issue_token` without
  touching routes.
- **Schema is created with `create_all`**, not migrations. `create_all` creates
  missing tables but never alters existing ones, so adding a column leaves an
  existing database behind and every read fails. The API detects this at startup
  and logs which columns are missing; in development, delete the database and
  let it be recreated (`backend/data/groundtruth.db`, or
  `docker compose down -v` for Postgres). A production deployment would use
  Alembic.
- **Windows/OneDrive**: keep `.venv` and `node_modules` out of OneDrive sync, or
  installs and file I/O are dramatically slower.

---

## Project layout

```
backend/
  app/
    api/routes/      query, evaluate, ingest, traces, voice, health
    config/          settings (single source for all configuration)
    db/              async engine + session
    evaluation/      ragas_eval, context_validation, factuality, reliability
    guardrails/      policies (deterministic) + engine (Guardrails AI)
    integrations/    moss/, livekit/
    models/          SQLAlchemy ORM
    prompts/         CRISPE registry + YAML templates
    retrieval/        chunking, embeddings, faiss_store, retriever
    schemas/         Pydantic contracts
    services/        orchestrator, llm, generation, ingestion, trace_store
    tracing/         latency timer
  tests/
frontend/
  src/app/           dashboard, evaluate, history, voice, API proxy
  src/components/    TrustReport, AppShell, IngestPanel, ui/
  src/lib/           typed API client + types
agent/               LiveKit voice agent
```
