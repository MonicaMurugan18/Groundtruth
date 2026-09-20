/**
 * Session endpoints for the browser.
 *
 * The JWT is never handed to client JavaScript. These handlers run on the
 * Next.js server: they call the backend, then store the token in an httpOnly
 * cookie that only the server-side proxy can read. That keeps the credential
 * out of `localStorage` and out of any XSS payload's reach.
 *
 * Three actions, one file, to keep the surface small:
 *   POST /api/auth/login     -> set session cookie
 *   POST /api/auth/register  -> create account, set session cookie
 *   POST /api/auth/logout    -> clear session cookie
 */

import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_API_URL ?? 'http://127.0.0.1:8000';

export const SESSION_COOKIE = 'gt_session';

type Action = 'login' | 'register' | 'logout';

function sessionCookieOptions(maxAgeSeconds: number) {
  return {
    httpOnly: true, // unreadable from client JS
    sameSite: 'lax' as const,
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: maxAgeSeconds,
  };
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ action: string }> },
) {
  const { action } = await context.params;

  if (action === 'logout') {
    const response = NextResponse.json({ ok: true });
    response.cookies.set(SESSION_COOKIE, '', sessionCookieOptions(0));
    return response;
  }

  if (action !== 'login' && action !== 'register') {
    return NextResponse.json({ detail: 'Unknown action.' }, { status: 404 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: 'Invalid request body.' }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/auth/${action satisfies Action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    });
  } catch {
    return NextResponse.json(
      {
        detail:
          `Could not reach the Groundtruth API at ${BACKEND_URL}. ` +
          'Start the backend and try again.',
      },
      { status: 502 },
    );
  }

  const payload = await upstream.json().catch(() => ({}));

  if (!upstream.ok) {
    // Pass the backend's own message through (it is deliberately generic for
    // failed logins, so this cannot be used to enumerate accounts).
    const detail =
      typeof payload?.detail === 'string'
        ? payload.detail
        : Array.isArray(payload?.detail)
          ? 'Please check the email and password format.'
          : 'Sign in failed.';
    return NextResponse.json({ detail }, { status: upstream.status });
  }

  const token: string | undefined = payload?.access_token;
  if (!token) {
    return NextResponse.json(
      { detail: 'The server did not return a session token.' },
      { status: 502 },
    );
  }

  const minutes: number = payload?.expires_in_minutes ?? 60;
  // Only the email is returned to the page; the token stays in the cookie.
  const response = NextResponse.json({ ok: true, email: payload?.email });
  response.cookies.set(SESSION_COOKIE, token, sessionCookieOptions(minutes * 60));
  return response;
}
