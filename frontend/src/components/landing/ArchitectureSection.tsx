'use client';

import {
  Activity,
  Database,
  Eye,
  FileCheck,
  Layers,
  Lock,
  Server,
  ShieldCheck,
} from 'lucide-react';
import { Reveal, SectionHeading } from './primitives';

/**
 * The architecture, as a single vertical flow.
 *
 * Deliberately shows component names and nothing else - no hostnames, keys,
 * project ids or credentials. The retrieval row is the one place the diagram
 * branches, because the Moss/FAISS fallback is a real behaviour worth showing
 * rather than a detail to hide.
 */

type Node = {
  label: string;
  sub?: string;
  icon: typeof Server;
  branch?: { primary: string; fallback: string };
};

const NODES: Node[] = [
  { label: 'User', sub: 'Text or voice', icon: Eye },
  { label: 'Next.js', sub: 'Dashboard + server-side proxy', icon: Layers },
  { label: 'FastAPI', sub: 'Orchestrator', icon: Server },
  {
    label: 'Retrieval',
    icon: Database,
    branch: { primary: 'Moss', fallback: 'FAISS fallback' },
  },
  { label: 'LLM', sub: 'Groq', icon: Activity },
  { label: 'Guardrails', sub: 'Input and output checks', icon: ShieldCheck },
  { label: 'RAGAS', sub: 'Grounding, relevance, retrieval quality', icon: FileCheck },
  { label: 'Trace', sub: 'Per-stage latency, persisted', icon: Lock },
];

export function ArchitectureSection() {
  return (
    <section id="architecture" className="scroll-mt-20 border-t border-border">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <Reveal>
          <SectionHeading
            eyebrow="Architecture"
            title="One pipeline. Complete visibility."
            subtitle="Every request follows the same path, and every stage writes to the same trace."
          />
        </Reveal>

        <div className="mx-auto mt-12 max-w-lg">
          {NODES.map((node, index) => {
            const Icon = node.icon;
            const last = index === NODES.length - 1;
            return (
              <Reveal key={node.label} delay={index * 70}>
                <div>
                  <div className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-raised text-info">
                      <Icon size={15} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground">
                        {node.label}
                      </p>
                      {node.sub && (
                        <p className="truncate text-xs text-faint">{node.sub}</p>
                      )}
                    </div>
                  </div>

                  {/* Retrieval is the one branching step: Moss, else FAISS. */}
                  {node.branch && (
                    <div className="mt-2 ml-11 grid grid-cols-2 gap-2">
                      <span className="rounded-lg border border-accent/30 bg-accent-soft px-2.5 py-1.5 text-center font-mono text-[11px] text-accent">
                        {node.branch.primary}
                      </span>
                      <span className="rounded-lg border border-border-strong bg-surface-raised px-2.5 py-1.5 text-center font-mono text-[11px] text-muted">
                        {node.branch.fallback}
                      </span>
                    </div>
                  )}

                  {!last && (
                    <div
                      className="relative mx-auto my-1.5 h-5 w-px bg-border"
                      aria-hidden
                    >
                      <span
                        className="gt-flow-dot absolute -left-[2px] top-0 h-[5px] w-[5px] rounded-full"
                        style={{
                          background: 'var(--info)',
                          animationDelay: `${index * 180}ms`,
                        }}
                      />
                    </div>
                  )}
                </div>
              </Reveal>
            );
          })}

          <Reveal delay={600}>
            <div className="mt-4 rounded-xl border border-reliable/25 bg-reliable-soft px-4 py-3 text-center">
              <p className="text-sm font-semibold tracking-wide text-reliable uppercase">
                Groundtruth result
              </p>
              <p className="mt-1 text-xs text-muted">
                Verdict, scores, guardrail outcome and latency — all traceable
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

/** Three closing value propositions. */
export function WhySection() {
  const blocks = [
    {
      title: 'Evidence first',
      copy: 'Every answer can be traced back to the retrieved context it was built from.',
      icon: Database,
    },
    {
      title: 'Runtime protection',
      copy: 'Guardrails help prevent unsafe or invalid interactions before they reach a user.',
      icon: ShieldCheck,
    },
    {
      title: 'Continuous evaluation',
      copy: 'Measure grounding, relevance, retrieval and latency instead of blindly trusting model output.',
      icon: Activity,
    },
  ];

  return (
    <section className="border-t border-border bg-surface/30">
      <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <Reveal>
          <SectionHeading
            eyebrow="Why Groundtruth"
            title="Reliability you can point at."
          />
        </Reveal>

        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {blocks.map((block, index) => {
            const Icon = block.icon;
            return (
              <Reveal key={block.title} delay={index * 110}>
                <div className="h-full rounded-xl border border-border bg-surface p-6">
                  <span className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-accent-soft text-accent">
                    <Icon size={18} />
                  </span>
                  <h3 className="text-base font-semibold text-foreground">
                    {block.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">
                    {block.copy}
                  </p>
                </div>
              </Reveal>
            );
          })}
        </div>
      </div>
    </section>
  );
}
