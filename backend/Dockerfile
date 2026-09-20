# Groundtruth backend — container image for Render.
#
# The deploy-critical decision here is that every large model is fetched at
# BUILD time, never at start-up. A cold container that downloads hundreds of
# megabytes while the platform is waiting for a health check is exactly what
# stalls and then kills a deploy, so those downloads are baked into the image
# and the running container needs no model network access at all.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NLTK_DATA=/usr/share/nltk_data

WORKDIR /app

# Compilers for any dependency without a manylinux wheel. Kept rather than
# purged: a build that fails at 3am costs more than the layer does.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# PyTorch, CPU build, installed BEFORE the requirements so that the
# transitive torch dependency is already satisfied when pip resolves them.
#
# The default PyPI torch wheel is CUDA-enabled: it drags in nvidia-cudnn,
# nvidia-cublas and the rest of the CUDA runtime, well over 2 GB of libraries
# that cannot be used on a CPU-only instance and that push the container past
# a 512 MB memory cap. The CPU index serves the same torch API, so
# sentence-transformers, transformers and detoxify all work unchanged.
RUN pip install --upgrade pip \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu

# Dependencies second, so edits to application code reuse this cached layer.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# NOTE: en_core_web_lg (~400 MB) is deliberately NOT installed.
#
# It belongs to DetectPII, through presidio-analyzer's default NLP engine.
# Loading it alongside torch does not fit in 512 MB. The guardrail engine
# checks for the model before constructing DetectPII and skips the validator
# when it is absent, so presidio never reaches its `spacy.cli.download`
# fallback and the container has no run-time download to blow up on.
#
# Every other guardrail is unaffected: the deterministic policy layer always
# runs, and ToxicLanguage is governed by DISABLE_TOXIC_LANGUAGE. To enable PII
# detection on an instance with the memory for it, add:
#     RUN python -m spacy download en_core_web_lg

# NLTK sentence tokeniser, needed by ToxicLanguage whenever it is enabled
# (DISABLE_TOXIC_LANGUAGE=false). Without it the validator raises on every
# call. Cheap, so it ships regardless of how the flag is set at run time.
RUN python -m nltk.downloader -d "$NLTK_DATA" punkt punkt_tab

COPY . .

# Documentation only; Render injects the real port via $PORT.
EXPOSE 8000

# Shell form so $PORT is expanded by the shell. The default keeps `docker run`
# working locally, where nothing sets PORT.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
