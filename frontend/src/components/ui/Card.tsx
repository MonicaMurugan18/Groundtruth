import type { ReactNode } from 'react';

export function Card({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-border bg-surface ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  icon: Icon,
  action,
}: {
  title: string;
  subtitle?: string;
  icon?: React.ComponentType<{ size?: number; className?: string }>;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-3.5">
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          {Icon && <Icon size={15} className="shrink-0 text-faint" />}
          {title}
        </h2>
        {subtitle && (
          <p className="mt-1 text-xs leading-relaxed text-faint">{subtitle}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function CardBody({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`px-5 py-4 ${className}`}>{children}</div>;
}

/** A labelled figure for the dashboard metric row. */
export function StatTile({
  label,
  value,
  sublabel,
  tone = 'neutral',
  icon: Icon,
}: {
  label: string;
  value: string;
  sublabel?: string;
  tone?: 'neutral' | 'reliable' | 'review' | 'failed' | 'accent';
  icon?: React.ComponentType<{ size?: number; className?: string }>;
}) {
  const valueColor = {
    neutral: 'text-foreground',
    reliable: 'text-reliable',
    review: 'text-review',
    failed: 'text-failed',
    accent: 'text-accent',
  }[tone];

  return (
    <Card className="px-4 py-3.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium tracking-wide text-faint uppercase">
          {label}
        </p>
        {Icon && <Icon size={14} className="shrink-0 text-faint" />}
      </div>
      <p
        className={`mt-2 font-mono text-2xl font-semibold tabular-nums ${valueColor}`}
      >
        {value}
      </p>
      {sublabel && <p className="mt-1 text-xs text-faint">{sublabel}</p>}
    </Card>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <Icon size={30} className="text-faint" />
      <h3 className="mt-3 text-sm font-semibold text-foreground">{title}</h3>
      <p className="mt-1.5 max-w-md text-sm leading-relaxed text-faint">
        {description}
      </p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
