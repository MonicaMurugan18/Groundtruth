"""Real wall-clock latency tracing for the evaluation pipeline.

Every duration Groundtruth reports originates here, measured with
:func:`time.perf_counter`. Nothing in this module can produce a number that was
not actually observed, which is what keeps the latency panel in the dashboard
honest.

Usage::

    trace = LatencyTrace()
    with trace.span("retrieval"):
        ...
    trace.to_dict()  # {"retrieval_ms": 118.4, "total_ms": 118.4, ...}
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

# Stage names that the API and dashboard treat as first-class columns.
RETRIEVAL = "retrieval"
LLM = "llm"
GUARDRAIL = "guardrail"
EVALUATION = "evaluation"
CONTEXT_VALIDATION = "context_validation"
# Second Moss stage: corroborating-evidence lookup on the generated answer.
MOSS_EVIDENCE = "moss_evidence"


@dataclass
class Span:
    """A single measured stage.

    ``accumulated_ms`` holds time from earlier runs of the same stage. A stage
    that executes more than once per request (the guardrail runs on both input
    and output) reports the total time spent in it, not just the last run.
    """

    name: str
    start: float
    end: float | None = None
    accumulated_ms: float = 0.0
    runs: int = 1

    @property
    def duration_ms(self) -> float | None:
        if self.end is None:
            return None
        return self.accumulated_ms + (self.end - self.start) * 1000.0


@dataclass
class LatencyTrace:
    """Collects per-stage timings for one request.

    The trace starts measuring the moment it is constructed, so ``total_ms``
    covers the whole request rather than only the sum of named spans (the
    difference is real orchestration overhead, and we want it visible).
    """

    _started: float = field(default_factory=time.perf_counter)
    _spans: dict[str, Span] = field(default_factory=dict)
    _finished: float | None = field(default=None)

    @contextmanager
    def span(self, name: str) -> Iterator[Span]:
        """Measure the wrapped block as stage ``name``.

        The span is closed even when the block raises, so a failed stage still
        reports how long it ran before failing.

        Re-entering the same stage name *accumulates* rather than replacing. The
        guardrail stage runs twice per request (once on the input, once on the
        output), and reporting only the second run would understate it.
        """
        previous = self._spans.get(name)
        span = Span(
            name=name,
            start=time.perf_counter(),
            accumulated_ms=(previous.duration_ms or 0.0) if previous else 0.0,
            runs=(previous.runs + 1) if previous else 1,
        )
        self._spans[name] = span
        try:
            yield span
        finally:
            span.end = time.perf_counter()

    def record_ms(self, name: str, duration_ms: float) -> None:
        """Record a duration measured elsewhere.

        Used for timings reported by an external system — notably Moss, which
        returns its own ``time_taken_ms`` for the search itself.
        """
        now = time.perf_counter()
        self._spans[name] = Span(name=name, start=now - (duration_ms / 1000.0), end=now)

    def finish(self) -> None:
        """Stop the total-duration clock. Idempotent."""
        if self._finished is None:
            self._finished = time.perf_counter()

    def get_ms(self, name: str) -> float | None:
        span = self._spans.get(name)
        return span.duration_ms if span else None

    @property
    def total_ms(self) -> float:
        end = self._finished if self._finished is not None else time.perf_counter()
        return (end - self._started) * 1000.0

    def to_dict(self) -> dict[str, float | None]:
        """Flat mapping for API responses and the ``latency`` DB column."""
        payload: dict[str, float | None] = {
            f"{name}_ms": span.duration_ms for name, span in self._spans.items()
        }
        payload["total_ms"] = round(self.total_ms, 2)
        return {
            key: (round(value, 2) if isinstance(value, float) else value)
            for key, value in payload.items()
        }
