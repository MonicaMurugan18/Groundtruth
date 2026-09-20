'use client';

import { AlertTriangle, CheckCircle2, Database, MinusCircle, Search } from 'lucide-react';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import type {
  EvaluationResponse,
  MossEvidence,
  MossStageInfo,
  MossStatus,
} from '@/lib/types';

/**
 * Moss usage for one interaction.
 *
 * The rule this panel enforces: Moss is never shown as successful when it
 * failed. The heading reflects which engine actually served retrieval, and a
 * failed call shows Moss's verbatim error rather than a generic message.
 */

const STATUS_STYLE: Record<MossStatus, { label: string; cls: string }> = {
  success: { label: 'SUCCESS', cls: 'text-reliable border-reliable/30 bg-reliable-soft' },
  empty: { label: 'NO MATCHES', cls: 'text-review border-review/30 bg-review-soft' },
  failed: { label: 'FAILED', cls: 'text-failed border-failed/30 bg-failed-soft' },
  not_configured: {
    label: 'NOT CONFIGURED',
    cls: 'text-muted border-border-strong bg-surface-raised',
  },
  skipped: { label: 'SKIPPED', cls: 'text-faint border-border-strong bg-surface-raised' },
};

function StatusChip({ status }: { status: MossStatus }) {
  const style = STATUS_STYLE[status] ?? STATUS_STYLE.skipped;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold tracking-wide ${style.cls}`}
    >
      {style.label}
    </span>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-xs">
      <span className="text-muted">{label}</span>
      <span className="font-mono tabular-nums text-foreground">{value}</span>
    </div>
  );
}

const STAGE_LABEL: Record<string, string> = {
  primary_retrieval: 'Primary retrieval',
  evidence_verification: 'Evidence verification',
};

function StageBlock({ stage }: { stage: MossStageInfo }) {
  const ran = stage.status === 'success' || stage.status === 'empty';
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-foreground">
          <Search size={12} className="text-faint" />
          {STAGE_LABEL[stage.stage] ?? stage.stage}
        </span>
        <StatusChip status={stage.status} />
      </div>

      {ran ? (
        <div className="space-y-1">
          <Row label="Results" value={stage.result_count} />
          {stage.index && <Row label="Index" value={stage.index} />}
          {/* Moss's own timing. Absent means Moss reported none - never guessed. */}
          <Row
            label="Moss engine time"
            value={stage.engine_ms === null ? '—' : `${stage.engine_ms.toFixed(1)} ms`}
          />
          {stage.wall_ms !== null && (
            <Row label="Round trip" value={`${stage.wall_ms.toFixed(0)} ms`} />
          )}
          {stage.top_score !== null && (
            <Row label="Top score" value={stage.top_score.toFixed(3)} />
          )}
        </div>
      ) : (
        <p className="text-xs leading-relaxed break-words text-faint">
          {stage.error ?? 'Moss was not called for this stage.'}
        </p>
      )}
    </div>
  );
}

function EvidenceBlock({ evidence }: { evidence: MossEvidence }) {
  const found = evidence.status === 'success';
  const Icon = found ? CheckCircle2 : evidence.status === 'empty' ? AlertTriangle : MinusCircle;
  const tone = found ? 'text-reliable' : evidence.status === 'empty' ? 'text-review' : 'text-faint';

  return (
    <div className="rounded-lg border border-border bg-surface-raised p-3">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Icon size={13} className={tone} />
        <span className="text-xs font-medium text-foreground">
          Corroborating evidence
        </span>
      </div>
      <p className="text-xs leading-relaxed text-muted">{evidence.reason}</p>
      {evidence.snippets.length > 0 && (
        <ul className="mt-2 space-y-1">
          {evidence.snippets.map((snippet, index) => (
            <li
              key={index}
              className="truncate rounded border border-border px-2 py-1 font-mono text-[10px] text-faint"
              title={snippet}
            >
              {snippet}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function MossPanel({ result }: { result: EvaluationResponse }) {
  const stages = result.moss_stages ?? [];
  const evidence = result.moss_evidence;
  if (stages.length === 0 && !evidence) return null;

  const servedByMoss = result.retrieval_backend === 'moss';

  return (
    <Card>
      <CardHeader
        title="Moss"
        subtitle="Semantic retrieval engine. Timings below are Moss's own measurements."
        icon={Database}
        action={
          <span
            className={`rounded-md border px-2 py-0.5 font-mono text-[11px] ${
              servedByMoss
                ? 'border-accent/30 bg-accent-soft text-accent'
                : 'border-border-strong bg-surface-raised text-muted'
            }`}
            title={
              servedByMoss
                ? 'Moss served this retrieval.'
                : 'Moss did not serve this retrieval; FAISS did.'
            }
          >
            {servedByMoss ? 'BACKEND: MOSS' : 'BACKEND: FAISS FALLBACK'}
          </span>
        }
      />
      <CardBody className="space-y-2.5">
        {stages.map((stage, index) => (
          <StageBlock key={`${stage.stage}-${index}`} stage={stage} />
        ))}
        {evidence && <EvidenceBlock evidence={evidence} />}
      </CardBody>
    </Card>
  );
}
