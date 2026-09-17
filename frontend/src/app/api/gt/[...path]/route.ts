/**
 * Server-side proxy to the Groundtruth orchestrator API.
 *
 * Every browser request goes through here rather than calling the backend
 * directly. That keeps the API token server-side: `GROUNDTRUTH_API_TOKEN` is a
 * plain (non-`NEXT_PUBLIC_`) variable, so it is never bundled into client
 * JavaScript, and the browser never sees a credential.
 *
 * It also means the backend does not need permissive CORS in production, since
 * requests arrive from the Next.js server rather than from the page origin.
 */

import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_API_URL ?? 'http://127.0.0.1:8000';
const API_TOKEN = process.env.GROUNDTRUTH_API_TOKEN ?? '';

/** Headers that must not be forwarded verbatim to the backend. */
const STRIPPED_REQUEST_HEADERS = new Set([
  'host',
  'connection',
  'content-length',
  'accept-encoding',
  // Never let a browser-supplied Authorization header through; we set our own.
  'authorization',
  'cookie',
]);

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const search = request.nextUrl.search;
  const target = `${BACKEND_URL}/${path.join('/')}${search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  if (API_TOKEN) {
    headers.set('Authorization', `Bearer ${API_TOKEN}`);
  }

  const method = request.method;
  const hasBody = method !== 'GET' && method !== 'HEAD';

  try {
    const upstream = await fetch(target, {
      method,
      headers,
      // Stream the body through unchanged so file uploads keep working.
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: 'no-store',
    });

    const body = await upstream.arrayBuffer();
    const responseHeaders = new Headers();
    const contentType = upstream.headers.get('content-type');
    if (contentType) responseHeaders.set('content-type', contentType);

    return new NextResponse(body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    // A connection failure here almost always means the backend is not running,
    // so say that plainly instead of surfacing a bare fetch error.
    return NextResponse.json(
      {
        detail:
          `Could not reach the Groundtruth API at ${BACKEND_URL}. ` +
          `Start the backend with: uvicorn app.main:app --reload`,
        error: error instanceof Error ? error.message : String(error),
      },
      { status: 502 },
    );
  }
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function POST(request: NextRequest, context: Context) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function DELETE(request: NextRequest, context: Context) {
  const { path } = await context.params;
  return proxy(request, path);
}
