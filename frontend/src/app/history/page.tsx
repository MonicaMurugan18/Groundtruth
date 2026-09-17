'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, History as HistoryIcon } from 'lucide-react';
import { PageHeader } from '@/components/AppShell';
import { Card, EmptyState } from '@/components/ui/Card';
import {
  ChannelBadge,
  GuardrailBadge,
  ReliabilityBadge,
} from '@/components/ui/StatusBadge';
import { api } from '@/lib/api';
import type { ReliabilityStatus, TraceListResponse } from '@/lib/types';

const PAGE_SIZE = 25;

const FILTERS: Array<{ value: ReliabilityStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'reliable', label: 'Reliable' },
  { value: 'needs_review', label: 'Needs review' },
  { value: 'failed', label: 'Failed' },
];

export default function HistoryPage() {
  const [data, setData] = useState<TraceListResponse | null>(null);
  const [filter, setFilter] = useState<ReliabilityStatus | 'all'>('all');
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(
        await api.traces({
          limit: PAGE_SIZE,
          offset,
          status: filter === 'all' ? undefined : filter,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [filter, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const total = data?.total ?? 0;
  const showingTo = Math.min(offset + PAGE_SIZE, total);

  return (
    <>
      <PageHeader
        title="Evaluation history"
        description="Every interaction Groundtruth has scored. Select a row to open its full trace."
      />

      <div className="mb-4 flex flex-wrap gap-1.5">
        {FILTERS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => {
              setFilter(value);
              setOffset(0);
            }}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === value
                ? 'bg-accent-soft text-accent'
                : 'bg-surface text-muted hover:text-foreground'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <Card className="overflow-hidden">
        {error ? (
          <EmptyState
            icon={HistoryIcon}
            title="Could not load history"
            description={error}
          />
        ) : !data ? (
          <div className="space-y-px p-1">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="h-12 animate-pulse rounded bg-surface-raised" />
            ))}
          </div>
        ) : data.items.length === 0 ? (
          <EmptyState
            icon={HistoryIcon}
            title="No evaluations match this filter"
            description={
              filter === 'all'
                ? 'Run an evaluation and it will appear here.'
                : 'Try a different status filter.'
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs tracking-wide text-faint uppercase">
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Query</th>
                  <th className="px-4 py-2.5 text-right font-medium">Faithful</th>
                  <th className="px-4 py-2.5 text-right font-medium">Relevance</th>
                  <th className="px-4 py-2.5 text-right font-medium">Latency</th>
                  <th className="px-4 py-2.5 font-medium">Guardrail</th>
                  <th className="px-4 py-2.5 font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.items.map((trace) => (
                  <tr
                    key={trace.evaluation_id}
                    className="transition-colors hover:bg-surface-raised"
                  >
                    <td className="px-4 py-2.5">
                      <ReliabilityBadge status={trace.status} size="sm" />
                    </td>
                    <td className="max-w-xs px-4 py-2.5">
                      <Link
                        href={`/history/${trace.evaluation_id}`}
                        className="flex items-center gap-1.5 truncate text-foreground hover:text-accent hover:underline"
                      >
                        <span className="truncate">{trace.query}</span>
                        <ChannelBadge channel={trace.channel} />
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs tabular-nums">
                      {trace.faithfulness === null
                        ? <span className="text-faint">—</span>
                        : `${(trace.faithfulness * 100).toFixed(0)}%`}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs tabular-nums">
                      {trace.answer_relevance === null
                        ? <span className="text-faint">—</span>
                        : `${(trace.answer_relevance * 100).toFixed(0)}%`}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs tabular-nums text-muted">
                      {trace.total_ms === null
                        ? '—'
                        : `${trace.total_ms.toFixed(0)}ms`}
                    </td>
                    <td className="px-4 py-2.5">
                      <GuardrailBadge status={trace.guardrail_status} size="sm" />
                    </td>
                    <td className="px-4 py-2.5 text-xs whitespace-nowrap text-faint">
                      {new Date(trace.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {data && total > PAGE_SIZE && (
        <div className="mt-3 flex items-center justify-between text-xs text-faint">
          <span>
            Showing {offset + 1}–{showingTo} of {total}
          </span>
          <div className="flex gap-1.5">
            <button
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0}
              className="flex items-center gap-1 rounded-lg bg-surface px-2.5 py-1.5 text-foreground disabled:opacity-40"
            >
              <ChevronLeft size={13} />
              Previous
            </button>
            <button
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={showingTo >= total}
              className="flex items-center gap-1 rounded-lg bg-surface px-2.5 py-1.5 text-foreground disabled:opacity-40"
            >
              Next
              <ChevronRight size={13} />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
