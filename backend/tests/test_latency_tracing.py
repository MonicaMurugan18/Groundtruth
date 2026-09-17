"""Latency tracing tests (hackathon test case 5).

Asserts that reported timings come from a real clock. The measured spans are
compared against actual elapsed sleeps, so a hardcoded or fabricated duration
would fail these tests.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.tracing.timer import LatencyTrace


def test_span_measures_real_elapsed_time():
    trace = LatencyTrace()
    with trace.span("retrieval"):
        time.sleep(0.05)
    trace.finish()

    retrieval_ms = trace.get_ms("retrieval")
    assert retrieval_ms is not None
    # Real measurement: at least the sleep, and not absurdly more.
    assert 45 <= retrieval_ms < 500


def test_distinct_stages_are_measured_independently():
    trace = LatencyTrace()
    with trace.span("retrieval"):
        time.sleep(0.02)
    with trace.span("llm"):
        time.sleep(0.06)
    trace.finish()

    assert trace.get_ms("llm") > trace.get_ms("retrieval")


def test_total_covers_all_stages_plus_overhead():
    trace = LatencyTrace()
    with trace.span("retrieval"):
        time.sleep(0.02)
    with trace.span("llm"):
        time.sleep(0.03)
    trace.finish()

    payload = trace.to_dict()
    stage_sum = payload["retrieval_ms"] + payload["llm_ms"]
    # Total must include orchestration overhead outside the named spans.
    assert payload["total_ms"] >= stage_sum


def test_span_is_closed_even_when_the_stage_raises():
    """A failed stage must still report how long it ran before failing."""
    trace = LatencyTrace()
    with pytest.raises(ValueError):
        with trace.span("llm"):
            time.sleep(0.02)
            raise ValueError("provider exploded")
    trace.finish()

    assert trace.get_ms("llm") is not None
    assert trace.get_ms("llm") >= 15


def test_repeated_stage_accumulates_instead_of_overwriting():
    """The guardrail stage runs twice per request (input, then output).

    Reporting only the second run would understate guardrail cost, so repeated
    spans of the same name must sum.
    """
    trace = LatencyTrace()
    with trace.span("guardrail"):
        time.sleep(0.03)
    time.sleep(0.05)  # unrelated work between the two guardrail runs
    with trace.span("guardrail"):
        time.sleep(0.03)
    trace.finish()

    guardrail_ms = trace.get_ms("guardrail")
    # ~60ms of guardrail work, and crucially NOT the ~110ms wall-clock span
    # between the two runs.
    assert 55 <= guardrail_ms < 95


def test_record_ms_accepts_externally_measured_duration():
    """Moss reports its own search time; it must survive into the trace."""
    trace = LatencyTrace()
    trace.record_ms("moss_engine", 7.5)
    trace.finish()
    assert trace.to_dict()["moss_engine_ms"] == pytest.approx(7.5, abs=0.5)


def test_finish_is_idempotent():
    trace = LatencyTrace()
    time.sleep(0.01)
    trace.finish()
    first = trace.total_ms
    time.sleep(0.02)
    trace.finish()
    assert trace.total_ms == pytest.approx(first, abs=0.001)


def test_to_dict_always_reports_total():
    trace = LatencyTrace()
    trace.finish()
    assert "total_ms" in trace.to_dict()


@pytest.mark.asyncio
async def test_spans_work_across_await_points():
    trace = LatencyTrace()
    with trace.span("evaluation"):
        await asyncio.sleep(0.04)
    trace.finish()
    assert trace.get_ms("evaluation") >= 35
