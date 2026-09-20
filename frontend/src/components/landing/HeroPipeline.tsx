'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, Cpu, Database, ShieldCheck, Sparkles } from 'lucide-react';
import { Connector, ExampleTag, StatusDot } from './primitives';

/**
 * The hero's animated pipeline.
 *
 * Nodes light up in sequence to show the shape of the real pipeline: retrieve,
 * generate, validate, evaluate. It is a *depiction* of the flow, labelled as an
 * example, and it makes no network calls - the real evaluation lives behind
 * login on /evaluate. That labelling matters: this product's whole claim is
 * that it does not present unverified things as results.
 */

type Stage = {
  key: string;
  label: string;
  detail: string;
  tech: string;
  icon: typeof Database;
};

const STAGES: Stage[] = [
  {
    key: 'retrieve',
    label: 'Retrieving context',
    detail: '"What is the refund period?"',
    tech: 'Moss / FAISS',
    icon: Database,
  },
  {
    key: 'generate',
    label: 'Generating response',
    detail: 'Grounded in retrieved passages only',
    tech: 'Groq',
    icon: Cpu,
  },
  {
    key: 'guard',
    label: 'Applying guardrails',
    detail: 'Input and output safety checks',
    tech: 'Guardrails AI',
    icon: ShieldCheck,
  },
  {
    key: 'evaluate',
    label: 'Evaluating response',
    detail: 'Grounding, relevance, retrieval quality',
    tech: 'RAGAS',
    icon: Sparkles,
  },
];

const CHECKS = [
  'Evidence found',
  'Guardrails passed',
  'Answer grounded in context',
];

export function HeroPipeline() {
  // -1 = idle; 0..n-1 = stage active; n = result shown.
  const [step, setStep] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

    if (reduced) {
      // Show the finished state rather than cycling.
      setStep(STAGES.length);
      return;
    }

    let timer: ReturnType<typeof setTimeout>;
    const advance = (next: number) => {
      setStep(next);
      // Hold the completed result a little longer before looping.
      const delay = next >= STAGES.length ? 3200 : 1100;
      timer = setTimeout(
        () => advance(next >= STAGES.length ? 0 : next + 1),
        delay,
      );
    };
    timer = setTimeout(() => advance(0), 400);
    return () => clearTimeout(timer);
  }, []);

  const done = step >= STAGES.length;

  return (
    <div
      ref={containerRef}
      className="relative w-full max-w-md"
      aria-label="Illustration of the Groundtruth evaluation pipeline"
    >
      <div className="rounded-2xl border border-border bg-surface/80 p-4 shadow-2xl backdrop-blur-sm sm:p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-faint uppercase">
            <StatusDot tone={done ? 'reliable' : 'info'} pulse={!done} />
            Reliability pipeline
          </span>
          <ExampleTag />
        </div>

        {/* Query */}
        <div className="rounded-lg border border-border bg-background px-3 py-2.5">
          <p className="mb-1 text-[10px] tracking-wide text-faint uppercase">
            User query
          </p>
          <p className="text-sm text-foreground">What is the refund period?</p>
        </div>

        <Connector active={step >= 0} />

        {/* Stages */}
        <ol className="space-y-0">
          {STAGES.map((stage, index) => {
            const state =
              done || step > index ? 'done' : step === index ? 'active' : 'idle';
            const Icon = stage.icon;
            return (
              <li key={stage.key}>
                <div
                  className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-all duration-500 ${
                    state === 'idle'
                      ? 'border-border bg-background opacity-45'
                      : state === 'active'
                        ? 'border-info/40 bg-info-soft'
                        : 'border-reliable/25 bg-background'
                  }`}
                >
                  <span
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors ${
                      state === 'done'
                        ? 'bg-reliable-soft text-reliable'
                        : state === 'active'
                          ? 'bg-info-soft text-info'
                          : 'bg-surface-raised text-faint'
                    }`}
                  >
                    {state === 'done' ? <Check size={14} /> : <Icon size={14} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-foreground">
                      {stage.label}
                    </p>
                    <p className="truncate text-[11px] text-faint">
                      {stage.detail}
                    </p>
                  </div>
                  <span className="hidden shrink-0 rounded border border-border-strong px-1.5 py-0.5 font-mono text-[9px] text-muted sm:block">
                    {stage.tech}
                  </span>
                </div>
                {index < STAGES.length - 1 && (
                  <Connector active={done || step > index} />
                )}
              </li>
            );
          })}
        </ol>

        <Connector active={done} />

        {/* Result */}
        <div
          className={`rounded-lg border px-3 py-3 transition-all duration-700 ${
            done
              ? 'border-reliable/35 bg-reliable-soft'
              : 'border-border bg-background opacity-40'
          }`}
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] tracking-wide text-faint uppercase">
              Result
            </span>
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase transition-colors ${
                done
                  ? 'border-reliable/40 bg-reliable-soft text-reliable'
                  : 'border-border-strong text-faint'
              }`}
            >
              {done ? 'Reliable' : 'Pending'}
            </span>
          </div>
          <ul className="space-y-1">
            {CHECKS.map((check, index) => (
              <li
                key={check}
                className="flex items-center gap-1.5 text-[11px] transition-opacity duration-500"
                style={{
                  opacity: done ? 1 : 0.35,
                  transitionDelay: `${index * 110}ms`,
                }}
              >
                <Check
                  size={11}
                  className={done ? 'text-reliable' : 'text-faint'}
                />
                <span className={done ? 'text-muted' : 'text-faint'}>
                  {check}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
