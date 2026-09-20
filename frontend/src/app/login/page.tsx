'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { Loader2, LogIn, ShieldCheck, UserPlus } from 'lucide-react';

/**
 * Sign in / sign up.
 *
 * The password is posted to a server-side route handler which exchanges it for
 * a JWT and stores that token in an httpOnly cookie. No token ever reaches
 * client JavaScript, so there is nothing here for an XSS payload to steal.
 */

type Mode = 'login' | 'register';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Where the user was heading before being bounced to /login.
  const next = searchParams.get('next') || '/dashboard';

  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        setError(payload?.detail ?? 'Sign in failed. Please try again.');
        return;
      }
      // Full navigation so the server re-reads the new session cookie.
      router.replace(next);
      router.refresh();
    } catch {
      setError('Could not reach the server. Is the application running?');
    } finally {
      setLoading(false);
    }
  }

  const isRegister = mode === 'register';

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft">
            <ShieldCheck size={19} className="text-accent" />
          </div>
          <div className="leading-tight">
            <p className="text-base font-semibold text-foreground">Groundtruth</p>
            <p className="text-xs text-faint">Agent reliability layer</p>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-surface p-6">
          <h1 className="text-sm font-semibold text-foreground">
            {isRegister ? 'Create an account' : 'Sign in'}
          </h1>
          <p className="mt-1 mb-5 text-xs leading-relaxed text-faint">
            {isRegister
              ? 'Accounts are local to this deployment.'
              : 'Sign in to view evaluations and run the reliability pipeline.'}
          </p>

          <form onSubmit={submit} className="space-y-3">
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-muted">Email</span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-faint focus:border-accent focus:outline-none"
              />
            </label>

            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-muted">Password</span>
              <input
                type="password"
                required
                minLength={isRegister ? 8 : 1}
                autoComplete={isRegister ? 'new-password' : 'current-password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={isRegister ? 'At least 8 characters' : '••••••••'}
                className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-faint focus:border-accent focus:outline-none"
              />
            </label>

            {error && (
              <p
                role="alert"
                className="rounded-lg border border-failed/30 bg-failed-soft px-3 py-2 text-xs leading-relaxed text-failed"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !email.trim() || !password}
              className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? (
                <Loader2 size={15} className="animate-spin" />
              ) : isRegister ? (
                <UserPlus size={15} />
              ) : (
                <LogIn size={15} />
              )}
              {loading
                ? isRegister
                  ? 'Creating account…'
                  : 'Signing in…'
                : isRegister
                  ? 'Create account'
                  : 'Sign in'}
            </button>
          </form>

          <button
            onClick={() => {
              setMode(isRegister ? 'login' : 'register');
              setError(null);
            }}
            className="mt-4 w-full text-center text-xs text-muted transition-colors hover:text-accent"
          >
            {isRegister
              ? 'Already have an account? Sign in'
              : 'No account yet? Create one'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  // useSearchParams requires a Suspense boundary during prerendering.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
