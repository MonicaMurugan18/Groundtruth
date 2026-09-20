'use client';

import {
  Activity,
  Cpu,
  Database,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { Reveal, SectionHeading } from './primitives';

/** The five pipeline stages, each labelled with the technology behind it. */

const STAGES = [
  {
    number: '01',
    name: 'Retrieve',
    copy: 'Find the most relevant evidence before trusting an agent’s response.',
    tech: 'Moss / FAISS',
    icon: Database,
  },
  {
    number: '02',
    name: 'Generate',
    copy: 'Generate responses using your configured AI model, grounded in the retrieved passages.',
    tech: 'Groq',
    icon: Cpu,
  },
  {
    number: '03',
    name: 'Guard',
    copy: 'Apply runtime safety and validation checks before responses reach the user.',
    tech: 'Guardrails AI',
    icon: ShieldCheck,
  },
  {
    number: '04',
    name: 'Evaluate',
    copy: 'Measure whether responses are grounded, relevant and supported by retrieved context.',
    tech: 'RAGAS',
    icon: Sparkles,
  },
  {
    number: '05',
    name: 'Trace',
    copy: 'Track latency, retrieval stages and evaluation results across every request.',
    tech: 'Runtime tracing',
    icon: Activity,
  },
];

export function SolutionSection() {
  return (
    <section
      id="how-it-works"
      className="scroll-mt-20 border-t border-border bg-surface/30"
    >
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <Reveal>
          <SectionHeading
            eyebrow="The solution"
            title="From AI generation to AI reliability."
            subtitle="Five stages run on every interaction. Each one is recorded, so a failure can be attributed to the stage that caused it."
          />
        </Reveal>

        <div className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {STAGES.map((stage, index) => {
            const Icon = stage.icon;
            return (
              <Reveal key={stage.number} delay={index * 80}>
                <article className="group h-full rounded-xl border border-border bg-surface p-5 transition-colors duration-300 hover:border-border-strong">
                  <div className="mb-4 flex items-start justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent">
                      <Icon size={17} />
                    </span>
                    <span className="font-mono text-xs text-faint">
                      {stage.number}
                    </span>
                  </div>
                  <h3 className="text-sm font-semibold tracking-wide text-foreground uppercase">
                    {stage.name}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">
                    {stage.copy}
                  </p>
                  <p className="mt-4 inline-block rounded-md border border-border-strong bg-surface-raised px-2 py-1 font-mono text-[10px] text-muted">
                    {stage.tech}
                  </p>
                </article>
              </Reveal>
            );
          })}

          {/* Closing tile keeps the 3-column grid balanced at 5 cards. */}
          <Reveal delay={400}>
            <div className="flex h-full flex-col justify-center rounded-xl border border-dashed border-border-strong bg-transparent p-5">
              <p className="text-sm leading-relaxed text-muted">
                Every stage writes to a single trace, so you can see{' '}
                <span className="text-foreground">
                  what was retrieved, what was answered and why it passed or
                  failed
                </span>{' '}
                — per request.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
