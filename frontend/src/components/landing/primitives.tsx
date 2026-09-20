'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Small building blocks shared by the landing sections.
 *
 * No animation dependency: the project has none, and these effects do not
 * justify adding one. Everything here is CSS plus an IntersectionObserver,
 * and the global prefers-reduced-motion rule neutralises the motion.
 */

/** Fades/slides its children in the first time they scroll into view. */
export function Reveal({
  children,
  delay = 0,
  className = '',
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    // No IntersectionObserver (or a very old browser): show immediately rather
    // than leaving the content permanently invisible.
    if (typeof IntersectionObserver === 'undefined') {
      setShown(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15, rootMargin: '0px 0px -40px 0px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      data-shown={shown}
      style={{ transitionDelay: `${delay}ms` }}
      className={`gt-reveal ${className}`}
    >
      {children}
    </div>
  );
}

/** Section heading with an optional eyebrow label. */
export function SectionHeading({
  eyebrow,
  title,
  subtitle,
  align = 'center',
}: {
  eyebrow?: string;
  title: React.ReactNode;
  subtitle?: string;
  align?: 'center' | 'left';
}) {
  const alignment = align === 'center' ? 'text-center mx-auto' : 'text-left';
  return (
    <div className={`max-w-2xl ${alignment}`}>
      {eyebrow && (
        <p className="mb-3 text-[11px] font-semibold tracking-[0.18em] text-accent uppercase">
          {eyebrow}
        </p>
      )}
      <h2 className="text-2xl leading-tight font-semibold text-balance text-foreground sm:text-3xl">
        {title}
      </h2>
      {subtitle && (
        <p className="mt-3 text-sm leading-relaxed text-pretty text-muted sm:text-base">
          {subtitle}
        </p>
      )}
    </div>
  );
}

/** A status dot that optionally pulses. */
export function StatusDot({
  tone = 'info',
  pulse = false,
}: {
  tone?: 'info' | 'reliable' | 'review' | 'faint';
  pulse?: boolean;
}) {
  const color = {
    info: 'var(--info)',
    reliable: 'var(--reliable)',
    review: 'var(--review)',
    faint: 'var(--faint)',
  }[tone];
  return (
    <span
      aria-hidden
      className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${pulse ? 'gt-pulse' : ''}`}
      style={
        {
          background: color,
          '--gt-pulse-color': color,
        } as React.CSSProperties
      }
    />
  );
}

/** Vertical connector between pipeline nodes, with a travelling dot. */
export function Connector({ active = true }: { active?: boolean }) {
  return (
    <div className="relative mx-auto h-6 w-px bg-border" aria-hidden>
      {active && (
        <span
          className="gt-flow-dot absolute -left-[2px] top-0 h-[5px] w-[5px] rounded-full"
          style={{ background: 'var(--info)' }}
        />
      )}
    </div>
  );
}

/**
 * Marks demonstration content.
 *
 * Used wherever the page shows an example rather than a live result, so a
 * viewer is never left guessing whether a number came from a real evaluation.
 */
export function ExampleTag({ label = 'Example' }: { label?: string }) {
  return (
    <span className="rounded-md border border-border-strong bg-surface-raised px-2 py-0.5 font-mono text-[10px] tracking-wide text-faint uppercase">
      {label}
    </span>
  );
}
