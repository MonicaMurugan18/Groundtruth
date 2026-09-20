'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { LayoutDashboard, Menu, ShieldCheck, X } from 'lucide-react';

/**
 * Sticky landing navbar.
 *
 * If a session cookie is already present the primary action becomes "Open
 * Dashboard" instead of "Get Started", so a signed-in visitor is not sent
 * through a login they do not need. `signedIn` is resolved by the server
 * component that renders this, rather than by probing an authenticated
 * endpoint from the browser: a public page should not fire a request that
 * 401s for every signed-out visitor.
 *
 * The cookie is only a presence check for labelling - it is not treated as
 * proof of anything, and every protected route still verifies the JWT
 * server-side.
 */

const LINKS = [
  { href: '#how-it-works', label: 'How It Works' },
  { href: '#reliability', label: 'Reliability' },
  { href: '#architecture', label: 'Architecture' },
];

export function LandingNav({ signedIn }: { signedIn: boolean }) {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const primary = signedIn
    ? { href: '/dashboard', label: 'Open Dashboard' }
    : { href: '/login', label: 'Get Started' };

  return (
    <header
      className={`sticky top-0 z-50 border-b transition-colors duration-300 ${
        scrolled
          ? 'border-border bg-background/85 backdrop-blur-md'
          : 'border-transparent bg-transparent'
      }`}
    >
      <nav className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-soft">
            <ShieldCheck size={15} className="text-accent" />
          </span>
          <span className="text-sm font-semibold tracking-[0.14em] text-foreground">
            GROUNDTRUTH
          </span>
        </Link>

        <div className="hidden items-center gap-7 md:flex">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="text-sm text-muted transition-colors hover:text-foreground"
            >
              {link.label}
            </a>
          ))}
        </div>

        <div className="hidden items-center gap-2 md:flex">
          {!signedIn && (
            <Link
              href="/login"
              className="rounded-lg px-3 py-1.5 text-sm text-muted transition-colors hover:text-foreground"
            >
              Sign In
            </Link>
          )}
          <Link
            href={primary.href}
            className="flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            {signedIn && <LayoutDashboard size={14} />}
            {primary.label}
          </Link>
        </div>

        <button
          onClick={() => setOpen((value) => !value)}
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          className="rounded-lg p-1.5 text-muted transition-colors hover:text-foreground md:hidden"
        >
          {open ? <X size={18} /> : <Menu size={18} />}
        </button>
      </nav>

      {open && (
        <div className="border-t border-border bg-background px-4 py-3 md:hidden">
          <div className="flex flex-col gap-1">
            {LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="rounded-lg px-2 py-2 text-sm text-muted hover:bg-surface hover:text-foreground"
              >
                {link.label}
              </a>
            ))}
            <Link
              href={primary.href}
              className="mt-2 rounded-lg bg-accent px-3 py-2 text-center text-sm font-medium text-white"
            >
              {primary.label}
            </Link>
          </div>
        </div>
      )}
    </header>
  );
}
