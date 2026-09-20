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

# Dependencies first, so edits to application code reuse this cached layer.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# spaCy's en_core_web_lg (~400 MB). It belongs to DetectPII, via
# presidio-analyzer's default NLP engine — NOT to ToxicLanguage. Presidio
# fetches it lazily on first AnalyzerEngine() construction, which start-up
# triggers through warm-up. Installing it here is what makes that start-up
# download impossible, and it keeps DetectPII fully active.
RUN python -m spacy download en_core_web_lg

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
