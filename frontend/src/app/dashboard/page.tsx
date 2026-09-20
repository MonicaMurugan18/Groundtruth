'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  Activity,
  CheckCircle2,
  FlaskConical,
  Mic,
  ShieldAlert,
  Timer,
  TriangleAlert,
  XCircle,
} from 'lucide-react';
import { PageHeader } from '@/components/AppShell';
import { Card, CardBody, CardHeader, EmptyState, StatTile } from '@/components/ui/Card';
import {
  ChannelBadge,
  GuardrailBadge,
  ReliabilityBadge,
} from '@/components/ui/StatusBadge';
import { api } from '@/lib/api';
import type { DashboardStats } from '@/lib/types';

/** Percentage formatter that distinguishes "no data" from zero. */
function percent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(0)}%`;
}

function millis(value: number | null): string {
  if (value === null) return '—';
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(0)} ms`;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .stats(8)
      .then(setStats)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) {
    return (
      <>
        <PageHeader
          title="Dashboard"
          description="Aggregate reliability of the agent across every evaluated interaction."
        />
        <Card>
          <EmptyState
            icon={XCircle}
            title="Could not load statistics"
            description={error}
          />
        </Card>
      </>
    );
  }

  if (!stats) {
    return (
      <>
        <PageHeader
          title="Dashboard"
          description="Aggregate reliability of the agent across every evaluated interaction."
        />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <div
              key={index}
              className="h-24 animate-pulse rounded-xl border border-border bg-surface"
            />
          ))}
        </div>
      </>
    );
  }

  const evaluated = stats.total_evaluations;
  const reliableRate =
    evaluated > 0 ? `${((stats.reliable_count / evaluated) * 100).toFixed(0)}% of all` : undefined;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Aggregate reliability of the agent across every evaluated interaction."
        action={
          <Link
            href="/evaluate"
            className="flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            <FlaskConical size={15} />
            New evaluation
          </Link>
        }
      />

      {evaluated === 0 ? (
        <Card>
          <EmptyState
            icon={Activity}
            title="No evaluations yet"
            description="Ingest a document and run a query. Every interaction is scored for faithfulness, relevance, retrieval quality, safety and latency, then recorded here."
            action={
              <Link
                href="/evaluate"
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white"
              >
                <FlaskConical size={15} />
                Run the first evaluation
              </Link>
            }
          />
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile
              label="Total evaluations"
              value={String(evaluated)}
              sublabel={
                stats.voice_evaluations > 0
                  ? `${stats.voice_evaluations} via voice`
                  : undefined
              }
              icon={Activity}
            />
            <StatTile
              label="Reliable"
              value={String(stats.reliable_count)}
              sublabel={reliableRate}
              tone="reliable"
              icon={CheckCircle2}
            />
            <StatTile
              label="Needs review"
              value={String(stats.needs_review_count)}
              tone="review"
              icon={TriangleAlert}
            />
            <StatTile
              label="Failed"
              value={String(stats.failed_count)}
              tone="failed"
              icon={XCircle}
            />

            <StatTile
              label="Avg faithfulness"
              value={percent(stats.avg_faithfulness)}
              sublabel="Support by retrieved context"
              icon={CheckCircle2}
            />
            <StatTile
              label="Avg relevance"
              value={percent(stats.avg_relevance)}
              sublabel="Answer addresses the question"
              icon={Activity}
            />
            <StatTile
              label="Guardrail violations"
              value={String(stats.guardrail_violations)}
              tone={stats.guardrail_violations > 0 ? 'review' : 'neutral'}
              sublabel="Blocked or flagged"
              icon={ShieldAlert}
            />
            <StatTile
              label="Avg latency"
              value={millis(stats.avg_latency_ms)}
              sublabel="End to end"
              icon={Timer}
            />
          </div>

          <div className="mt-5">
            <Card>
              <CardHeader
                title="Recent evaluations"
                icon={Activity}
                action={
                  <Link
                    href="/history"
                    className="text-xs font-medium text-accent hover:underline"
                  >
                    View all
                  </Link>
                }
              />
              <CardBody className="px-0 py-0">
                <ul className="divide-y divide-border">
                  {stats.recent.map((trace) => (
                    <li key={trace.evaluation_id}>
                      <Link
                        href={`/history/${trace.evaluation_id}`}
                        className="flex items-center justify-between gap-4 px-5 py-3 transition-colors hover:bg-surface-raised"
                      >
                        <div className="flex min-w-0 items-center gap-2.5">
                          <ReliabilityBadge status={trace.status} size="sm" />
                          <span className="truncate text-sm text-foreground">
                            {trace.query}
                          </span>
                          {trace.channel === 'voice' && (
                            <ChannelBadge channel={trace.channel} />
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-3 font-mono text-xs text-faint">
                          <span title="Faithfulness">
                            {trace.faithfulness === null
                              ? '—'
                              : `${(trace.faithfulness * 100).toFixed(0)}%`}
                          </span>
                          <span title="Total latency">
                            {trace.total_ms === null
                              ? '—'
                              : `${trace.total_ms.toFixed(0)}ms`}
                          </span>
                          <GuardrailBadge status={trace.guardrail_status} size="sm" />
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          </div>
        </>
      )}

      {stats.voice_evaluations === 0 && evaluated > 0 && (
        <p className="mt-4 flex items-center gap-1.5 text-xs text-faint">
          <Mic size={12} />
          No voice interactions recorded yet. Voice turns appear here alongside
          typed ones once the LiveKit agent is running.
        </p>
      )}
    </>
  );
}
