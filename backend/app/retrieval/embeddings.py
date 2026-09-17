"""Hugging Face sentence embeddings.

The model is loaded lazily and cached for the process lifetime: loading
all-MiniLM-L6-v2 takes seconds, and paying that per request would dominate the
retrieval latency we are trying to measure honestly.

Vectors are L2-normalised on output so a FAISS inner-product index yields cosine
similarity directly, which is what the context-validation thresholds assume.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_model: Any | None = None
_model_lock = threading.Lock()


def get_embedding_model() -> Any:
    """Return the cached SentenceTransformer, loading it on first use."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                settings = get_settings()
                logger.info(
                    "Loading embedding model %s on %s (first call downloads weights)",
                    settings.embedding_model,
                    settings.embedding_device,
                )
                _model = SentenceTransformer(
                    settings.embedding_model, device=settings.embedding_device
                )
    return _model


def embedding_dimension() -> int:
    return int(get_embedding_model().get_sentence_embedding_dimension())


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts into an L2-normalised float32 matrix."""
    if not texts:
        return np.zeros((0, embedding_dimension()), dtype=np.float32)

    model = get_embedding_model()
    vectors = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vectors, dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    """Embed a single query into a 1 x dim matrix."""
    return embed_texts([text])


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors, clamped to [-1, 1]."""
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0.0:
        return 0.0
    return float(np.clip(float(np.dot(a, b)) / denominator, -1.0, 1.0))
