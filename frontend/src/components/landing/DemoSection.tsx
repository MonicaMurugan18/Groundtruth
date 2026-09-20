'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import { ExampleTag, Reveal, SectionHeading, StatusDot } from './primitives';

/**
 * "See Groundtruth Think" - an illustrated run of the pipeline.
 *
 * The numbers are fixed example values, not a live evaluation, and the section
 * says so in three places: an Example tag, the heading copy, and the note
 * beneath the metrics. The same note states the faithfulness caveat that the
 * product itself enforces - grounding is not proof of real-world truth.
 */

const PHASES = ['Retrieving', 'Context found', 'Generating', 'Validating', 'Evaluating'];

const METRICS = [
  { label: 'Faithfulness', value: 100, hint: 'Every claim is supported by the retrieved context.' },
  { label: 'Answer relevance', value: 89, hint: 'The answer addresses the question that was asked.' },
  { label: 'Context quality', value: 100, hint: 'The retrieved passages were actually useful.' },
];

function useCountUp(target: number, run: boolean) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!run) return;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      setValue(target);
      return;
    }
    let frame = 0;
    const total = 38;
    const id = setInterval(() => {
      frame += 1;
      // Ease-out so the number settles rather than stopping abruptly.
      const progress = 1 - Math.pow(1 - frame / total, 3);
      setValue(Math.round(target * progress));
      if (frame >= total) clearInterval(id);
    }, 16);
    return () => clearInterval(id);
  }, [target, run]);
  return value;
}

function Metric({ label, value, hint, run }: { label: string; value: number; hint: string; run: boolean }) {
  const shown = useCountUp(value, run);
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <p className="text-[11px] text-muted">{label}</p>
      <p className="mt-1 font-mono text-2xl font-semibold tabular-nums text-reliable">
        {shown}%
      </p>
      <p className="mt-1.5 text-[11px] leading-relaxed text-faint">{hint}</p>
    </div>
  );
}

export function DemoSection() {
  const ref = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState(-1);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      setPhase(PHASES.length);
      return;
    }
    const timers: ReturnType<typeof setTimeout>[] = [];
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        observer.disconnect();
        PHASES.forEach((_, index) =>
          timers.push(setTimeout(() => setPhase(index), 400 + index * 520)),
        );
        timers.push(
          setTimeout(() => setPhase(PHASES.length), 400 + PHASES.length * 520),
        );
      },
      { threshold: 0.25 },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      timers.forEach(clearTimeout);
    };
  }, []);

  const done = phase >= PHASES.length;

  return (
    <section id="reliability" className="scroll-mt-20 border-t border-border">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <Reveal>
          <SectionHeading
            eyebrow="Walkthrough"
            title="See Groundtruth think."
            subtitle="An illustration of one evaluation, stage by stage. The values below are fixed example figures, not a live run."
          />
        </Reveal>

        <div ref={ref} className="mx-auto mt-12 max-w-3xl">
          <Reveal>
            <div className="rounded-2xl border border-border bg-surface p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5 text-[11px] tracking-wide text-faint uppercase">
                  <StatusDot tone={done ? 'reliable' : 'info'} pulse={!done} />
                  {done ? 'Evaluation complete' : 'Running evaluation'}
                </span>
                <ExampleTag label="Example evaluation" />
              </div>

              <div className="rounded-lg border border-border bg-background px-3 py-2.5">
                <p className="mb-1 text-[10px] tracking-wide text-faint uppercase">
                  User query
                </p>
                <p className="text-sm text-foreground">
                  What is the refund period?
                </p>
              </div>

              {/* Phase strip */}
              <ol className="mt-4 flex flex-wrap gap-1.5">
                {PHASES.map((name, index) => {
                  const state =
                    done || phase > index ? 'done' : phase === index ? 'active' : 'idle';
                  return (
                    <li
                      key={name}
                      className={`rounded-md border px-2.5 py-1 text-[11px] transition-all duration-500 ${
                        state === 'idle'
                          ? 'border-border text-faint opacity-50'
                          : state === 'active'
                            ? 'border-info/40 bg-info-soft text-info'
                            : 'border-reliable/25 bg-reliable-soft text-reliable'
                      }`}
                    >
                      {name}
                    </li>
                  );
                })}
              </ol>

              {/* Result */}
              <div
                className="mt-5 transition-opacity duration-700"
                style={{ opacity: done ? 1 : 0.25 }}
              >
                <div className="mb-3 flex items-center gap-2">
                  <CheckCircle2 size={15} className="text-reliable" />
                  <span className="text-sm font-semibold tracking-wide text-reliable uppercase">
                    Reliable
                  </span>
                </div>

                <div className="grid gap-2.5 sm:grid-cols-3">
                  {METRICS.map((metric) => (
                    <Metric key={metric.label} {...metric} run={done} />
                  ))}
                </div>
              </div>

              <p className="mt-4 flex gap-2 rounded-lg border border-border bg-surface-raised px-3 py-2.5 text-[11px] leading-relaxed text-faint">
                <Info size={13} className="mt-px shrink-0" />
                <span>
                  Groundtruth evaluates whether an agent&apos;s response is
                  supported by the context supplied to it.{' '}
                  <span className="text-muted">
                    Faithfulness is a grounding measure, not independent proof of
                    real-world truth.
                  </span>
                </span>
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/** Reliable vs needs-review, side by side. No invented statistics. */
export function ReliabilityStates() {
  const states = [
    {
      title: 'Reliable',
      tone: 'reliable' as const,
      icon: CheckCircle2,
      points: [
        'Evidence supports the response',
        'Guardrails passed',
        'Evaluation completed',
      ],
    },
    {
      title: 'Needs review',
      tone: 'review' as const,
      icon: AlertTriangle,
      points: [
        'Evidence does not sufficiently support the response',
        'Unsupported claim detected',
        'Human review may be required',
      ],
    },
  ];

  return (
    <section className="border-t border-border bg-surface/30">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <Reveal>
          <SectionHeading
            eyebrow="Outcomes"
            title="Two answers. Two very different verdicts."
            subtitle="Groundtruth does not only score a response — it states which outcome applies and why."
          />
        </Reveal>

        <div className="mx-auto mt-12 grid max-w-3xl gap-4 md:grid-cols-2">
          {states.map((state, index) => {
            const Icon = state.icon;
            const border =
              state.tone === 'reliable' ? 'border-reliable/25' : 'border-review/25';
            const bg =
              state.tone === 'reliable' ? 'bg-reliable-soft' : 'bg-review-soft';
            const text =
              state.tone === 'reliable' ? 'text-reliable' : 'text-review';
            return (
              <Reveal key={state.title} delay={index * 120}>
                <div className={`h-full rounded-xl border ${border} ${bg} p-5`}>
                  <div className="mb-4 flex items-center gap-2">
                    <Icon size={16} className={text} />
                    <span
                      className={`text-sm font-semibold tracking-wide uppercase ${text}`}
                    >
                      {state.title}
                    </span>
                  </div>
                  <ul className="space-y-2.5">
                    {state.points.map((point) => (
                      <li
                        key={point}
                        className="flex gap-2 text-sm leading-relaxed text-muted"
                      >
                        <span className={`mt-1.5 h-1 w-1 shrink-0 rounded-full ${state.tone === 'reliable' ? 'bg-reliable' : 'bg-review'}`} />
                        {point}
                      </li>
                    ))}
                  </ul>
                </div>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}
