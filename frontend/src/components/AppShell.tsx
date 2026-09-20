'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Activity,
  FlaskConical,
  History,
  LayoutDashboard,
  LogOut,
  Mic,
  ShieldCheck,
} from 'lucide-react';
import { api } from '@/lib/api';
import type { CapabilitiesResponse } from '@/lib/types';

const NAV = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/evaluate', label: 'Evaluate', icon: FlaskConical },
  { href: '/history', label: 'History', icon: History },
  { href: '/voice', label: 'Voice', icon: Mic },
];

/**
 * Application shell: navigation plus a live integration-status strip.
 *
 * The status strip is not decoration. It reports which integrations are
 * actually configured, so an operator can tell at a glance whether a low score
 * reflects the agent's behaviour or a missing credential.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // The landing and login pages are standalone - no sidebar, no integration
  // strip. Everything else gets the application chrome.
  const isStandalone = pathname === '/login' || pathname === '/';
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(
    null,
  );
  const [offline, setOffline] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  async function signOut() {
    setSigningOut(true);
    // Clearing the httpOnly cookie is the whole logout: tokens are stateless,
    // so once the browser stops sending it, every request is unauthenticated.
    await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
    window.location.href = '/login';
  }

  useEffect(() => {
    // Hooks run before the standalone early-return below, so without this the
    // public landing page would fire an authenticated capabilities request it
    // has no use for (and which 401s for a signed-out visitor).
    if (isStandalone) return;
    let cancelled = false;
    api
      .capabilities()
      .then((data) => !cancelled && setCapabilities(data))
      .catch(() => !cancelled && setOffline(true));
    return () => {
      cancelled = true;
    };
  }, [isStandalone]);

  if (isStandalone) return <>{children}</>;

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-border bg-surface lg:h-screen lg:w-60 lg:border-r lg:border-b-0">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-soft">
            <ShieldCheck size={17} className="text-accent" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-foreground">Groundtruth</p>
            <p className="text-[11px] text-faint">Agent reliability layer</p>
          </div>
        </div>

        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? 'page' : undefined}
                className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm whitespace-nowrap transition-colors ${
                  active
                    ? 'bg-accent-soft font-medium text-accent'
                    : 'text-muted hover:bg-surface-raised hover:text-foreground'
                }`}
              >
                <Icon size={16} />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto hidden border-t border-border px-3 py-3 lg:block">
          <button
            onClick={signOut}
            disabled={signingOut}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-muted transition-colors hover:bg-surface-raised hover:text-foreground disabled:opacity-50"
          >
            <LogOut size={16} />
            {signingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>

        <div className="hidden border-t border-border px-4 py-4 lg:block">
          <p className="mb-2.5 flex items-center gap-1.5 text-[11px] font-medium tracking-wide text-faint uppercase">
            <Activity size={11} />
            Integrations
          </p>
          {offline ? (
            <p className="text-xs leading-relaxed text-failed">
              API unreachable. Start the backend on port 8000.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {capabilities?.components.map((component) => (
                <li
                  key={component.name}
                  className="flex items-center justify-between gap-2 text-xs"
                  title={component.detail}
                >
                  <span className="text-muted capitalize">{component.name}</span>
                  <span
                    className={
                      component.configured ? 'text-reliable' : 'text-faint'
                    }
                  >
                    {component.configured ? 'ready' : 'not set'}
                  </span>
                </li>
              )) ?? <li className="text-xs text-faint">Checking…</li>}
            </ul>
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1 lg:h-screen lg:overflow-y-auto">
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </div>
      </main>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-foreground">{title}</h1>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">
          {description}
        </p>
      </div>
      {action}
    </header>
  );
}
