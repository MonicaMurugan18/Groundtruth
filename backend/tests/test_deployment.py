"""Deployment-shape tests for the container image.

These do not build the image - that needs a Docker daemon and several minutes.
They assert the properties that, when wrong, produce a deploy that fails only
after a long build: a runtime model download, a port the platform cannot reach,
or a secret baked into a layer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
DOCKERFILE = BACKEND_DIR / "Dockerfile"
DOCKERIGNORE = BACKEND_DIR / ".dockerignore"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    assert DOCKERFILE.is_file(), "backend/Dockerfile is missing"
    return DOCKERFILE.read_text(encoding="utf-8")


def test_uses_python_311(dockerfile: str):
    """guardrails-ai caps below 3.14 and the project targets 3.11."""
    assert re.search(r"^FROM python:3\.11", dockerfile, re.MULTILINE)


def test_installs_the_existing_requirements(dockerfile: str):
    assert "requirements.txt" in dockerfile
    assert re.search(r"pip install .*-r requirements\.txt", dockerfile)


def test_start_command_binds_all_interfaces_on_the_platform_port(dockerfile: str):
    """Render routes to $PORT; binding elsewhere makes the service unreachable."""
    cmd = re.search(r"^CMD (.+)$", dockerfile, re.MULTILINE)
    assert cmd, "Dockerfile has no CMD"
    line = cmd.group(1)

    assert "uvicorn app.main:app" in line
    assert "--host 0.0.0.0" in line
    assert "PORT" in line
    # Shell form, not exec form: exec form would pass the literal string
    # "${PORT:-8000}" to uvicorn instead of expanding it.
    assert not line.lstrip().startswith("["), "exec-form CMD will not expand $PORT"


def test_spacy_model_is_baked_in_so_startup_never_downloads_it(dockerfile: str):
    """The 400 MB model must be fetched at build time, not on a cold start.

    en_core_web_lg belongs to DetectPII (presidio-analyzer's default NLP
    engine), not to ToxicLanguage. Presidio downloads it lazily when
    AnalyzerEngine() is first constructed, which warm-up triggers during
    start-up - the stall this image exists to prevent.
    """
    assert re.search(r"spacy download en_core_web_lg", dockerfile)

    build_step = dockerfile.index("spacy download en_core_web_lg")
    app_copy = dockerfile.index("COPY . .")
    assert build_step < app_copy, "model must be installed during the build"


def test_nltk_tokeniser_is_present_for_toxic_language(dockerfile: str):
    """ToxicLanguage raises on every call without punkt_tab when enabled."""
    assert "nltk.downloader" in dockerfile
    assert "punkt_tab" in dockerfile


# --- The image must not carry secrets ---------------------------------------


@pytest.fixture(scope="module")
def dockerignore() -> str:
    assert DOCKERIGNORE.is_file(), "backend/.dockerignore is missing"
    return DOCKERIGNORE.read_text(encoding="utf-8")


def test_dockerignore_excludes_env_files(dockerignore: str):
    """`COPY . .` would otherwise bake backend/.env into a readable layer."""
    patterns = {
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert ".env" in patterns
    assert ".venv/" in patterns


def test_env_file_is_ignored_by_git():
    """Defence in depth: the image is only as safe as the build context.

    backend/.env legitimately exists on a developer machine, so this asserts
    that git ignores it rather than that it is absent.
    """
    gitignore = (BACKEND_DIR.parent / ".gitignore").read_text(encoding="utf-8")
    ignored = {
        line.strip()
        for line in gitignore.splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert ".env" in ignored
