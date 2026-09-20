'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Bot, Check, ScanLine, X } from 'lucide-react';
import { ExampleTag, Reveal, SectionHeading } from './primitives';

/**
 * The problem, shown rather than described.
 *
 * A confident-sounding answer is scanned against the evidence and the
 * contradiction is surfaced. Everything here is a depiction - no API call -
 * and it is labelled as an example, because a product about not overstating
 * results should not overstate its own marketing.
 */

const STEPS = [
  { label: 'Context retrieved', ok: true },
  { label: 'Evidence compared', ok: true },
  { label: 'Unsupported claim detected', ok: false },
];

export function ProblemSection() {
  const [step, setStep] = useState(-1);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      setStep(STEPS.length);
      return;
    }

    let timers: ReturnType<typeof setTimeout>[] = [];
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        observer.disconnect();
        STEPS.forEach((_, index) => {
          timers.push(setTimeout(() => setStep(index), 700 + index * 750));
        });
        timers.push(setTimeout(() => setStep(STEPS.length), 700 + STEPS.length * 750));
      },
      { threshold: 0.3 },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      timers.forEach(clearTimeout);
    };
  }, []);

  const finished = step >= STEPS.length;

  return (
    <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
      <Reveal>
        <SectionHeading
          eyebrow="The problem"
          title={
            <>
              AI can answer instantly.
              <br />
              <span className="text-muted">
                That doesn&apos;t mean it answered correctly.
              </span>
            </>
          }
          subtitle="AI agents can generate confident responses that are unsupported, unsafe, or disconnected from the evidence they were given."
        />
      </Reveal>

      <div ref={ref} className="mx-auto mt-12 grid max-w-3xl gap-4 md:grid-cols-2">
        {/* The confident answer */}
        <Reveal>
          <div className="h-full rounded-xl border border-border bg-surface p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-[11px] tracking-wide text-faint uppercase">
                <Bot size={12} />
                AI agent
              </span>
              <ExampleTag />
            </div>
            <p className="rounded-lg border border-border bg-background px-3 py-3 text-sm text-foreground">
              &ldquo;The refund period is 30&nbsp;days.&rdquo;
            </p>
            <p className="mt-3 text-xs leading-relaxed text-faint">
              Fluent, specific and confident. Nothing about the response itself
              tells you whether the number is real.
            </p>
          </div>
        </Reveal>

        {/* The verification */}
        <Reveal delay={120}>
          <div className="relative h-full overflow-hidden rounded-xl border border-border bg-surface p-4">
            {!finished && step >= 0 && (
              <span
                className="gt-scan pointer-events-none absolute inset-x-0 top-0 h-px"
                style={
                  {
                    background:
                      'linear-gradient(90deg, transparent, var(--info), transparent)',
                    '--gt-scan-distance': '190px',
                  } as React.CSSProperties
                }
                aria-hidden
              />
            )}

            <div className="mb-3 flex items-center gap-1.5 text-[11px] tracking-wide text-faint uppercase">
              <ScanLine size={12} />
              {finished ? 'Verification complete' : 'Scanning response…'}
            </div>

            <ul className="space-y-2">
              {STEPS.map((item, index) => {
                const visible = step >= index;
                return (
                  <li
                    key={item.label}
                    className="flex items-center gap-2 text-xs transition-all duration-500"
                    style={{
                      opacity: visible ? 1 : 0.25,
                      transform: visible ? 'none' : 'translateX(-6px)',
                    }}
                  >
                    {item.ok ? (
                      <Check size={13} className="shrink-0 text-reliable" />
                    ) : (
                      <X size={13} className="shrink-0 text-failed" />
                    )}
                    <span className={item.ok ? 'text-muted' : 'text-failed'}>
                      {item.label}
                    </span>
                  </li>
                );
              })}
            </ul>

            <div
              className="mt-4 rounded-lg border border-review/30 bg-review-soft px-3 py-2.5 transition-all duration-700"
              style={{ opacity: finished ? 1 : 0 }}
            >
              <p className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-review uppercase">
                <AlertTriangle size={12} />
                Needs review
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-muted">
                The response claims 30&nbsp;days, but the retrieved evidence
                states 7&nbsp;days.
              </p>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
