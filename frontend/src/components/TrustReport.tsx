'use client';

import {
  AlertTriangle,
  BookOpen,
  Bot,
  FileSearch,
  Gauge,
  Info,
  MessageSquare,
  ScrollText,
  ShieldCheck,
  Timer,
} from 'lucide-react';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { MossPanel } from '@/components/MossPanel';
import { ScoreBar } from '@/components/ui/ScoreBar';
import {
  BackendBadge,
  ContextBadge,
  GuardrailBadge,
  ReliabilityBadge,
} from '@/components/ui/StatusBadge';
import type { EvaluationResponse, LatencyBreakdown } from '@/lib/types';

/**
 * The full trust report for one interaction.
 *
 * Structured to answer, in order, the questions an engineer actually asks when
 * an agent misbehaves: what did it retrieve, what did it answer, was that
 * answer supported, why did it pass or fail, was there a safety issue, and
 * where did the time go.
 */

export function TrustReport({ result }: { result: EvaluationResponse }) {
  return (
    <div className="space-y-4">
      <VerdictBanner result={result} />

      {result.warnings.length > 0 && <WarningList warnings={result.warnings} />}

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <RagTriad result={result} />
        </div>
        <div className="space-y-4 lg:col-span-2">
          <ScorePanel result={result} />
          <MossPanel result={result} />
          <GuardrailPanel result={result} />
          <FactualPanel result={result} />
          <LatencyPanel latency={result.latency} />
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function VerdictBanner({ result }: { result: EvaluationResponse }) {
  const tone = {
    reliable: 'border-reliable/30 bg-reliable-soft',
    needs_review: 'border-review/30 bg-review-soft',
    failed: 'border-failed/30 bg-failed-soft',
  }[result.status];

  return (
    <div className={`rounded-xl border px-5 py-4 ${tone}`}>
      <div className="flex flex-wrap items-center gap-2.5">
        <ReliabilityBadge status={result.status} />
        <BackendBadge backend={result.retrieval_backend} />
        <span className="font-mono text-xs text-faint">
          {result.latency.total_ms.toFixed(0)} ms total
        </span>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-foreground">
        {result.explanation}
      </p>
    </div>
  );
}

function WarningList({ warnings }: { warnings: string[] }) {
  return (
    <div className="rounded-xl border border-review/30 bg-review-soft px-4 py-3">
      <p className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-review uppercase">
        <AlertTriangle size={12} />
        Pipeline warnings
      </p>
      <ul className="mt-2 space-y-1">
        {warnings.map((warning, index) => (
          <li key={index} className="text-xs leading-relaxed text-muted">
            • {warning}
          </li>
        ))}
      </ul>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function RagTriad({ result }: { result: EvaluationResponse }) {
  return (
    <>
      <Card>
        <CardHeader title="User query" icon={MessageSquare} />
        <CardBody>
          <p className="text-sm leading-relaxed text-foreground">
            {result.query}
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={`Retrieved context (${result.contexts.length})`}
          subtitle="The exact passages supplied to the model. Faithfulness is measured against these and nothing else."
          icon={BookOpen}
          action={<ContextBadge status={result.context_validation.status} size="sm" />}
        />
        <CardBody className="space-y-3">
          <p className="rounded-lg border border-border bg-surface-raised px-3 py-2 text-xs leading-relaxed text-muted">
            <FileSearch size={12} className="mr-1.5 inline text-faint" />
            {result.context_validation.reason}
          </p>

          {result.contexts.length === 0 ? (
            <p className="py-2 text-sm text-faint">
              Nothing was retrieved for this query.
            </p>
          ) : (
            <ol className="space-y-2.5">
              {result.contexts.map((chunk, index) => (
                <li
                  key={index}
                  className="rounded-lg border border-border bg-surface-raised p-3"
                >
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-faint">
                      [{index + 1}] {chunk.source ?? 'unknown source'}
                    </span>
                    {chunk.score !== null && (
                      <span className="font-mono text-[11px] text-faint">
                        sim {chunk.score.toFixed(3)}
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-relaxed whitespace-pre-wrap text-muted">
                    {chunk.text}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Agent answer" icon={Bot} />
        <CardBody>
          {result.answer ? (
            <p className="text-sm leading-relaxed whitespace-pre-wrap text-foreground">
              {result.answer}
            </p>
          ) : (
            <p className="text-sm text-faint">
              No answer was produced for this query.
            </p>
          )}
        </CardBody>
      </Card>
    </>
  );
}

/* -------------------------------------------------------------------------- */

function ScorePanel({ result }: { result: EvaluationResponse }) {
  return (
    <Card>
      <CardHeader title="Evaluation scores" icon={Gauge} />
      <CardBody className="space-y-4">
        <ScoreBar
          label="Faithfulness"
          metric={result.faithfulness}
          hint="Is every claim in the answer supported by the retrieved context? This does not measure whether the context itself is true."
        />
        <ScoreBar
          label="Answer relevance"
          metric={result.answer_relevance}
          hint="Does the answer actually address the question that was asked?"
        />
        <ScoreBar
          label="Context / retrieval quality"
          metric={result.context_precision}
          hint="Were the retrieved chunks actually useful for answering, or mostly noise?"
        />
      </CardBody>
    </Card>
  );
}

function GuardrailPanel({ result }: { result: EvaluationResponse }) {
  const { guardrail } = result;
  return (
    <Card>
      <CardHeader
        title="Guardrails"
        icon={ShieldCheck}
        action={<GuardrailBadge status={guardrail.status} size="sm" />}
      />
      <CardBody className="space-y-2">
        <p className="text-xs leading-relaxed text-muted">{guardrail.reason}</p>
        {guardrail.triggered.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {guardrail.triggered.map((validator) => (
              <span
                key={validator}
                className="rounded border border-border-strong bg-surface-raised px-1.5 py-0.5 font-mono text-[10px] text-muted"
              >
                {validator}
              </span>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

/**
 * Factual verification, presented separately from faithfulness on purpose.
 * A high faithfulness score proves grounding, not truth.
 */
function FactualPanel({ result }: { result: EvaluationResponse }) {
  const factual = result.factual_verification;
  const assessed = factual.status === 'ok';

  return (
    <Card>
      <CardHeader title="Factual verification" icon={ScrollText} />
      <CardBody className="space-y-2">
        {assessed ? (
          <div className="flex items-center gap-2">
            <span
              className={`text-sm font-semibold ${
                factual.correct ? 'text-reliable' : 'text-failed'
              }`}
            >
              {factual.correct ? 'Matches reference' : 'Contradicts reference'}
            </span>
            {factual.score !== null && (
              <span className="font-mono text-xs text-faint">
                {(factual.score * 100).toFixed(0)}%
              </span>
            )}
          </div>
        ) : (
          <p className="flex items-start gap-1.5 text-xs font-medium text-faint">
            <Info size={12} className="mt-0.5 shrink-0" />
            Not assessed
          </p>
        )}
        <p className="text-xs leading-relaxed text-faint">{factual.reason}</p>
      </CardBody>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */

const LATENCY_STAGES: Array<{ key: keyof LatencyBreakdown; label: string }> = [
  { key: 'retrieval_ms', label: 'Retrieval' },
  { key: 'moss_engine_ms', label: 'Moss engine' },
  { key: 'context_validation_ms', label: 'Context validation' },
  { key: 'llm_ms', label: 'LLM generation' },
  { key: 'guardrail_ms', label: 'Guardrails' },
  { key: 'evaluation_ms', label: 'Evaluation' },
];

export function LatencyPanel({ latency }: { latency: LatencyBreakdown }) {
  const total = latency.total_ms || 1;
  const stages = LATENCY_STAGES.map(({ key, label }) => ({
    label,
    value: typeof latency[key] === 'number' ? (latency[key] as number) : null,
  })).filter((stage) => stage.value !== null);

  return (
    <Card>
      <CardHeader
        title="Latency breakdown"
        subtitle="Measured per stage with a real clock."
        icon={Timer}
      />
      <CardBody className="space-y-2.5">
        {stages.map((stage) => (
          <div key={stage.label} className="space-y-1">
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-muted">{stage.label}</span>
              <span className="font-mono tabular-nums text-foreground">
                {stage.value!.toFixed(0)} ms
              </span>
            </div>
            <div className="h-1 w-full overflow-hidden rounded-full bg-border">
              <div
                className="h-full rounded-full bg-info"
                style={{
                  width: `${Math.min((stage.value! / total) * 100, 100)}%`,
                }}
              />
            </div>
          </div>
        ))}

        <div className="flex items-baseline justify-between border-t border-border pt-2.5 text-xs">
          <span className="font-medium text-foreground">Total</span>
          <span className="font-mono text-sm font-semibold tabular-nums text-foreground">
            {latency.total_ms.toFixed(0)} ms
          </span>
        </div>
      </CardBody>
    </Card>
  );
}
