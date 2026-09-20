"""Start-up must not cost a model load.

Uvicorn imports the ASGI app and runs lifespan start-up *before* it opens the
listening socket, so anything slow at import time happens while the platform is
still scanning for an open port. Importing app.main once pulled in torch,
transformers and sentence_transformers by way of
``langchain_text_splitters`` - 48s, against a Render port-scan timeout.

These run in a subprocess on purpose. sys.modules is process-wide, so another
test that happens to touch the embedding model first would make an in-process
assertion pass for the wrong reason.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

# Pulled in transitively by the heavy paths; none should load to serve /health.
HEAVY_MODULES = ("torch", "sentence_transformers", "transformers", "faiss")

TIME_BUDGET_SECONDS = 25.0


def _run(script: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"subprocess failed\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr[-3000:]}"
    )
    return result.stdout


def test_importing_the_app_does_not_load_ai_models():
    """The import uvicorn performs before binding must stay cheap."""
    out = _run(
        f"""
        import sys, time
        start = time.perf_counter()
        import app.main  # noqa: F401
        elapsed = time.perf_counter() - start
        loaded = [m for m in {HEAVY_MODULES!r} if m in sys.modules]
        print("ELAPSED", elapsed)
        print("LOADED", ",".join(loaded))
        """
    )
    loaded = next(l for l in out.splitlines() if l.startswith("LOADED"))[7:]
    elapsed = float(next(l for l in out.splitlines() if l.startswith("ELAPSED"))[8:])

    assert loaded == "", f"importing app.main loaded heavy modules: {loaded}"
    assert elapsed < TIME_BUDGET_SECONDS, (
        f"importing app.main took {elapsed:.1f}s; uvicorn pays this before it "
        "opens the port, which is what times out the platform's port scan"
    )


def test_health_responds_without_loading_ai_models():
    """/health must answer while the AI stack is still cold."""
    out = _run(
        f"""
        import sys, os
        os.environ["WARMUP_ON_STARTUP"] = "false"
        os.environ["DISABLE_TOXIC_LANGUAGE"] = "true"
        from fastapi.testclient import TestClient
        from app.main import create_app

        with TestClient(create_app()) as client:
            response = client.get("/health")
            print("STATUS", response.status_code)
            print("BODY", response.json()["status"])

        loaded = [m for m in {HEAVY_MODULES!r} if m in sys.modules]
        print("LOADED", ",".join(loaded))
        """
    )
    lines = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)

    assert lines.get("STATUS") == "200"
    assert lines.get("BODY") == "ok"
    # The point of the test: a healthy liveness probe proves nothing about the
    # models, and must not be gated on them either.
    assert lines.get("LOADED", "") == "", (
        f"serving /health loaded heavy modules: {lines.get('LOADED')}"
    )


def test_warmup_is_on_by_default():
    """The Render switch must not silently change existing behaviour."""
    from app.config.settings import get_settings

    assert get_settings().model_copy(update={"warmup_on_startup": True}).warmup_on_startup
    # Default comes from the field, not the local .env, so read the model field.
    from app.config.settings import Settings

    assert Settings.model_fields["warmup_on_startup"].default is True


@pytest.mark.parametrize("module", HEAVY_MODULES)
def test_no_module_level_heavy_imports_in_app_package(module: str):
    """Guards the regression directly: a top-level import anywhere in app/."""
    import pathlib
    import re

    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if re.match(rf"^(import {module}|from {module}[. ])", line):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, f"module-level {module} import in: {offenders}"
