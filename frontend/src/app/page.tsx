import { cookies } from 'next/headers';
import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

import { ArchitectureSection, WhySection } from '@/components/landing/ArchitectureSection';
import { ClosingSection, LandingFooter } from '@/components/landing/ClosingSection';
import { DemoSection, ReliabilityStates } from '@/components/landing/DemoSection';
import { HeroPipeline } from '@/components/landing/HeroPipeline';
import { LandingNav } from '@/components/landing/LandingNav';
import { ProblemSection } from '@/components/landing/ProblemSection';
import { SolutionSection } from '@/components/landing/SolutionSection';

/**
 * Public landing page.
 *
 * Reachable without a session (see `PUBLIC_PATHS` in src/proxy.ts). The
 * authenticated dashboard lives at /dashboard and is unchanged.
 *
 * Nothing on this page calls the evaluation API. Every figure shown is a fixed
 * illustration and is labelled as an example, because a product whose entire
 * claim is "we do not present unverified output as a result" should not break
 * that rule in its own marketing.
 *
 * The only session-dependent detail is the navbar's primary button. Its state
 * is resolved here from the cookie's presence - the same presence check
 * src/proxy.ts makes, used only to pick a label - so the browser never has to
 * probe an authenticated endpoint that would 401 for every visitor.
 */

const SESSION_COOKIE = 'gt_session';

export const metadata = {
  title: 'Groundtruth — Trust Every AI Decision',
  description:
    'Groundtruth verifies what your AI agents say before you trust what they do. Retrieve evidence, detect unsupported claims, apply runtime guardrails, measure reliability and trace every decision.',
};

export default async function LandingPage() {
  const signedIn = Boolean((await cookies()).get(SESSION_COOKIE)?.value);

  return (
    <div className="min-h-screen overflow-x-hidden bg-background">
      <LandingNav signedIn={signedIn} />

      {/* ---------------------------------------------------------------- */}
      {/* Hero                                                              */}
      {/* ---------------------------------------------------------------- */}
      <section className="relative">
        <div className="gt-grid pointer-events-none absolute inset-0" aria-hidden />

        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pt-14 pb-20 sm:px-6 lg:grid-cols-2 lg:gap-10 lg:pt-20 lg:pb-28">
          <div>
            <div
              className="gt-rise inline-flex items-center gap-2 rounded-full border border-border bg-surface/70 px-3 py-1"
              style={{ animationDelay: '60ms' }}
            >
              <span
                className="gt-pulse h-1.5 w-1.5 rounded-full"
                style={
                  {
                    background: 'var(--info)',
                    '--gt-pulse-color': 'rgba(88,166,255,.45)',
                  } as React.CSSProperties
                }
              />
              <span className="text-[11px] font-medium tracking-[0.16em] text-muted uppercase">
                AI Agent Reliability Platform
              </span>
            </div>

            <h1
              className="gt-rise mt-6 text-4xl leading-[1.08] font-semibold text-balance text-foreground sm:text-5xl lg:text-6xl"
              style={{ animationDelay: '140ms' }}
            >
              Trust Every
              <br />
              AI Decision.
            </h1>

            <p
              className="gt-rise mt-5 max-w-lg text-base leading-relaxed text-pretty text-muted sm:text-lg"
              style={{ animationDelay: '220ms' }}
            >
              Groundtruth verifies what your AI agents say before you trust what
              they do.
            </p>

            <p
              className="gt-rise mt-4 max-w-lg text-sm leading-relaxed text-pretty text-faint"
              style={{ animationDelay: '290ms' }}
            >
              Retrieve evidence. Detect unsupported claims. Apply runtime
              guardrails. Measure reliability. Trace every decision.
            </p>

            <div
              className="gt-rise mt-8 flex flex-col gap-3 sm:flex-row"
              style={{ animationDelay: '360ms' }}
            >
              <Link
                href="/login"
                className="group inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
              >
                Start Evaluating
                <ArrowRight
                  size={15}
                  className="transition-transform duration-300 group-hover:translate-x-0.5"
                />
              </Link>
              <a
                href="#how-it-works"
                className="inline-flex items-center justify-center rounded-lg border border-border bg-surface px-5 py-2.5 text-sm font-medium text-foreground transition-colors hover:border-border-strong"
              >
                See How It Works
              </a>
            </div>
          </div>

          <div
            className="gt-fade flex justify-center lg:justify-end"
            style={{ animationDelay: '420ms' }}
          >
            <HeroPipeline />
          </div>
        </div>
      </section>

      <ProblemSection />
      <SolutionSection />
      <DemoSection />
      <ReliabilityStates />
      <ArchitectureSection />
      <WhySection />
      <ClosingSection />
      <LandingFooter />
    </div>
  );
}
