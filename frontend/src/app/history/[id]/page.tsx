'use client';

import Link from 'next/link';
import { use, useEffect, useState } from 'react';
import { ArrowLeft, FileQuestion } from 'lucide-react';
import { PageHeader } from '@/components/AppShell';
import { TrustReport } from '@/components/TrustReport';
import { Card, EmptyState } from '@/components/ui/Card';
import { api } from '@/lib/api';
import type { EvaluationResponse } from '@/lib/types';

/**
 * Full trace view for a single stored evaluation.
 *
 * In Next.js 16 route `params` is a Promise, so it is unwrapped with `use()`
 * here (this is a client component).
 */
export default function TraceDetailPage({
  params,
}: PageProps<'/history/[id]'>) {
  const { id } = use(params);
  const [result, setResult] = useState<EvaluationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .trace(id)
      .then(setResult)
      .catch((err: Error) => setError(err.message));
  }, [id]);

  return (
    <>
      <Link
        href="/history"
        className="mb-4 inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-accent"
      >
        <ArrowLeft size={13} />
        Back to history
      </Link>

      <PageHeader
        title="Evaluation trace"
        description={
          result
            ? `Recorded ${new Date(result.created_at).toLocaleString()} · ${result.evaluation_id}`
            : 'Loading the stored trace…'
        }
      />

      {error ? (
        <Card>
          <EmptyState
            icon={FileQuestion}
            title="Trace not found"
            description={error}
          />
        </Card>
      ) : !result ? (
        <div className="space-y-4">
          <div className="h-24 animate-pulse rounded-xl border border-border bg-surface" />
          <div className="h-72 animate-pulse rounded-xl border border-border bg-surface" />
        </div>
      ) : (
        <TrustReport result={result} />
      )}
    </>
  );
}
