import { AlertCircle, MinusCircle } from 'lucide-react';
import type { MetricScore } from '@/lib/types';

/**
 * Renders one evaluation metric.
 *
 * The important behaviour here is the null case. A metric whose `status` is not
 * `ok` has no value, and showing it as "0%" would be a lie — it would look like
 * a failing score when in fact nothing was measured. Those cases render an
 * explicit "not computed" state with the reason attached.
 */

const THRESHOLD_GOOD = 0.7;
const THRESHOLD_FAIR = 0.5;

function barColor(value: number): string {
  if (value >= THRESHOLD_GOOD) return 'var(--reliable)';
  if (value >= THRESHOLD_FAIR) return 'var(--review)';
  return 'var(--failed)';
}

const STATUS_LABEL: Record<string, string> = {
  unavailable: 'Not computed',
  error: 'Evaluation error',
  not_applicable: 'Not applicable',
};

export function ScoreBar({
  label,
  metric,
  hint,
}: {
  label: string;
  metric: MetricScore;
  hint?: string;
}) {
  const hasValue = metric.status === 'ok' && metric.value !== null;

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-foreground">{label}</span>
          {hint && (
            <span
              className="cursor-help text-faint"
              title={hint}
              aria-label={hint}
            >
              <AlertCircle size={13} aria-hidden="true" />
            </span>
          )}
        </div>

        {hasValue ? (
          <span
            className="font-mono text-lg font-semibold tabular-nums"
            style={{ color: barColor(metric.value!) }}
          >
            {(metric.value! * 100).toFixed(0)}%
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-xs font-medium text-faint">
            <MinusCircle size={13} aria-hidden="true" />
            {STATUS_LABEL[metric.status] ?? 'Unavailable'}
          </span>
        )}
      </div>

      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-border"
        role="meter"
        aria-label={label}
        aria-valuenow={hasValue ? Math.round(metric.value! * 100) : undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={hasValue ? undefined : 'not computed'}
      >
        {hasValue ? (
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{
              width: `${Math.max(metric.value! * 100, 1.5)}%`,
              background: barColor(metric.value!),
            }}
          />
        ) : (
          // A hatched track makes "no measurement" visually distinct from a
          // genuine low score, which would be a filled red bar.
          <div
            className="h-full w-full opacity-40"
            style={{
              backgroundImage:
                'repeating-linear-gradient(45deg, var(--border-strong) 0 4px, transparent 4px 8px)',
            }}
          />
        )}
      </div>

      {!hasValue && metric.detail && (
        <p className="text-xs leading-relaxed text-faint">{metric.detail}</p>
      )}
    </div>
  );
}
