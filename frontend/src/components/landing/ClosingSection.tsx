'use client';

import Link from 'next/link';
import { ArrowRight, ShieldCheck } from 'lucide-react';
import { Reveal } from './primitives';

/** Final call to action and footer. */

export function ClosingSection() {
  return (
    <section className="border-t border-border">
      <div className="mx-auto max-w-3xl px-4 py-24 text-center sm:px-6 sm:py-32">
        <Reveal>
          <h2 className="text-3xl leading-tight font-semibold text-balance text-foreground sm:text-4xl">
            Don&apos;t just generate AI answers.
            <br />
            <span className="text-accent">Know why you can trust them.</span>
          </h2>
          <p className="mx-auto mt-4 max-w-md text-sm leading-relaxed text-pretty text-muted sm:text-base">
            Evaluate your agent before your users have to.
          </p>
          <Link
            href="/login"
            className="group mt-8 inline-flex items-center gap-2 rounded-lg bg-accent px-6 py-3 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            Enter Groundtruth
            <ArrowRight
              size={16}
              className="transition-transform duration-300 group-hover:translate-x-0.5"
            />
          </Link>
        </Reveal>
      </div>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className="border-t border-border bg-surface/30">
      <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 px-4 py-10 sm:flex-row sm:items-center sm:px-6">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-soft">
              <ShieldCheck size={15} className="text-accent" />
            </span>
            <span className="text-sm font-semibold tracking-[0.14em] text-foreground">
              GROUNDTRUTH
            </span>
          </div>
          <p className="mt-2 text-xs text-faint">
            AI Agent Reliability, Security &amp; Evaluation
          </p>
        </div>

        <div className="flex items-center gap-5">
          <Link
            href="/login"
            className="text-sm text-muted transition-colors hover:text-foreground"
          >
            Sign In
          </Link>
          <Link
            href="/login"
            className="text-sm text-muted transition-colors hover:text-foreground"
          >
            Get Started
          </Link>
        </div>
      </div>
    </footer>
  );
}
