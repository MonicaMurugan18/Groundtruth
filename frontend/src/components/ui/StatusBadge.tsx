import {
  CheckCircle2,
  CircleSlash,
  MicOff,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  TriangleAlert,
  XCircle,
} from 'lucide-react';
import type {
  ContextValidationStatus,
  GuardrailStatus,
  ReliabilityStatus,
} from '@/lib/types';

/**
 * Status chips.
 *
 * Every chip pairs a colour with both an icon and a text label, so the meaning
 * survives colour-blindness and greyscale printing. Colour alone is never the
 * only signal.
 */

type Tone = 'reliable' | 'review' | 'failed' | 'info' | 'neutral';

const TONE_STYLES: Record<Tone, string> = {
  reliable: 'bg-reliable-soft text-reliable border-reliable/30',
  review: 'bg-review-soft text-review border-review/30',
  failed: 'bg-failed-soft text-failed border-failed/30',
  info: 'bg-info-soft text-info border-info/30',
  neutral: 'bg-surface-raised text-muted border-border-strong',
};

const SIZES = {
  sm: 'px-2 py-0.5 text-[11px] gap-1',
  md: 'px-2.5 py-1 text-xs gap-1.5',
} as const;

function Chip({
  tone,
  icon: Icon,
  label,
  size = 'md',
  title,
}: {
  tone: Tone;
  icon: React.ComponentType<{ size?: number; 'aria-hidden'?: boolean }>;
  label: string;
  size?: keyof typeof SIZES;
  title?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full border font-semibold uppercase tracking-wide whitespace-nowrap ${TONE_STYLES[tone]} ${SIZES[size]}`}
      title={title}
    >
      <Icon size={size === 'sm' ? 11 : 13} aria-hidden />
      {label}
    </span>
  );
}

const RELIABILITY: Record<
  ReliabilityStatus,
  { tone: Tone; label: string; icon: typeof CheckCircle2 }
> = {
  reliable: { tone: 'reliable', label: 'Reliable', icon: CheckCircle2 },
  needs_review: { tone: 'review', label: 'Needs review', icon: TriangleAlert },
  failed: { tone: 'failed', label: 'Failed', icon: XCircle },
};

export function ReliabilityBadge({
  status,
  size = 'md',
}: {
  status: ReliabilityStatus;
  size?: keyof typeof SIZES;
}) {
  const config = RELIABILITY[status];
  return <Chip {...config} size={size} />;
}

const GUARDRAIL: Record<
  GuardrailStatus,
  { tone: Tone; label: string; icon: typeof ShieldCheck }
> = {
  pass: { tone: 'reliable', label: 'Pass', icon: ShieldCheck },
  review: { tone: 'review', label: 'Review', icon: ShieldAlert },
  block: { tone: 'failed', label: 'Blocked', icon: ShieldX },
};

export function GuardrailBadge({
  status,
  size = 'md',
}: {
  status: GuardrailStatus;
  size?: keyof typeof SIZES;
}) {
  const config = GUARDRAIL[status];
  return <Chip {...config} size={size} />;
}

const CONTEXT: Record<
  ContextValidationStatus,
  { tone: Tone; label: string; icon: typeof CheckCircle2; title: string }
> = {
  relevant: {
    tone: 'reliable',
    label: 'Relevant',
    icon: CheckCircle2,
    title: 'The retrieved context can support an answer to this question.',
  },
  insufficient: {
    tone: 'review',
    label: 'Insufficient',
    icon: TriangleAlert,
    title: 'On-topic, but missing the specific detail the question asks for.',
  },
  irrelevant: {
    tone: 'failed',
    label: 'Irrelevant',
    icon: XCircle,
    title: 'The retrieved context is about a different subject entirely.',
  },
  empty: {
    tone: 'neutral',
    label: 'No context',
    icon: CircleSlash,
    title: 'Retrieval returned nothing at all.',
  },
};

export function ContextBadge({
  status,
  size = 'md',
}: {
  status: ContextValidationStatus;
  size?: keyof typeof SIZES;
}) {
  const config = CONTEXT[status];
  return <Chip {...config} size={size} />;
}

export function ChannelBadge({ channel }: { channel: 'text' | 'voice' }) {
  if (channel === 'voice') {
    return <Chip tone="info" icon={MicOff} label="Voice" size="sm" />;
  }
  return null;
}

/** Which engine actually served retrieval — Moss or the FAISS fallback. */
export function BackendBadge({ backend }: { backend: string }) {
  if (backend === 'none') return null;
  const isMoss = backend === 'moss';
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] ${
        isMoss
          ? 'border-accent/30 bg-accent-soft text-accent'
          : 'border-border-strong bg-surface-raised text-muted'
      }`}
      title={
        isMoss
          ? 'Retrieval was served by Moss.'
          : 'Retrieval was served by the local FAISS index, not Moss.'
      }
    >
      {backend}
    </span>
  );
}
