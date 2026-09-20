/**
 * Route protection.
 *
 * Named `proxy` (not `middleware`) per Next.js 16, which renamed the convention
 * and runs it on the Node runtime.
 *
 * This is a gate, not the security boundary. It checks only that a session
 * cookie is present, so an unauthenticated visitor lands on /login instead of a
 * blank dashboard. The real enforcement is the backend's JWT verification: a
 * forged or expired cookie still fails there with 401, because this never
 * validates the token itself.
 */

import { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIE = 'gt_session';

/** Paths reachable without a session. '/' is the public landing page. */
const PUBLIC_PATHS = ['/', '/login'];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Never gate the auth endpoints themselves, or sign-in could not happen.
  if (pathname.startsWith('/api/auth')) {
    return NextResponse.next();
  }

  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  const isPublic = PUBLIC_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );

  if (!hasSession && !isPublic) {
    // API calls get JSON, not a redirect. If a session expires while a page is
    // open, a redirect would hand the page an HTML login form where it expects
    // JSON, surfacing as a parse error instead of "you are signed out".
    if (pathname.startsWith('/api/')) {
      return NextResponse.json(
        { detail: 'Your session has expired. Please sign in again.' },
        { status: 401 },
      );
    }
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    // Preserve the destination so sign-in can return the user to it.
    url.searchParams.set('next', pathname);
    return NextResponse.redirect(url);
  }

  // Already signed in and visiting /login: send them straight to the dashboard.
  // The landing page stays reachable while signed in - it is marketing, not a
  // gate - so only /login redirects.
  if (hasSession && pathname === '/login') {
    const url = request.nextUrl.clone();
    url.pathname = '/dashboard';
    url.search = '';
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  /*
   * Protect application pages and the API proxy, while leaving Next's own
   * assets alone. The API proxy is matched too so an unauthenticated fetch is
   * redirected rather than reaching the backend without a token.
   */
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|svg|webp|ico)$).*)'],
};
