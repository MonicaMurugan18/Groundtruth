/**
 * Typed client for the Groundtruth API.
 *
 * All calls go to `/api/gt/...`, the same-origin proxy in
 * `src/app/api/gt/[...path]/route.ts`, which attaches the API token
 * server-side. No credential is ever present in client code.
 */

import type {
  CapabilitiesResponse,
  DashboardStats,
  EvaluationResponse,
  IngestResponse,
  TraceListResponse,
  VoiceTokenResponse,
} from './types';

const BASE = '/api/gt';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...init?.headers,
    },
    cache: 'no-store',
  });

  if (!response.ok) {
    // FastAPI reports errors as {detail: ...}; surface that rather than a
    // generic status message so the UI can explain what actually went wrong.
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === 'string') {
        detail = payload.detail;
      } else if (Array.isArray(payload?.detail)) {
        detail = payload.detail
          .map((item: { loc?: string[]; msg?: string }) =>
            `${item.loc?.slice(1).join('.') ?? 'field'}: ${item.msg ?? 'invalid'}`,
          )
          .join('; ');
      }
    } catch {
      // Body was not JSON; keep the status-based message.
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  capabilities: () => request<CapabilitiesResponse>('/health/capabilities'),

  stats: (recent = 8) => request<DashboardStats>(`/stats?recent=${recent}`),

  traces: (params: {
    limit?: number;
    offset?: number;
    status?: string;
    channel?: string;
  } = {}) => {
    const query = new URLSearchParams();
    if (params.limit) query.set('limit', String(params.limit));
    if (params.offset) query.set('offset', String(params.offset));
    if (params.status) query.set('status', params.status);
    if (params.channel) query.set('channel', params.channel);
    const suffix = query.toString() ? `?${query}` : '';
    return request<TraceListResponse>(`/traces${suffix}`);
  },

  trace: (id: string) => request<EvaluationResponse>(`/traces/${id}`),

  query: (body: {
    query: string;
    top_k?: number;
    reference_answer?: string;
  }) =>
    request<EvaluationResponse>('/query', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  evaluateTriad: (body: {
    query: string;
    contexts: string[];
    answer: string;
    reference_answer?: string;
  }) =>
    request<EvaluationResponse>('/evaluate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  ingestText: (body: { name: string; text: string }) =>
    request<IngestResponse>('/ingest/text', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  ingestFile: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<IngestResponse>('/ingest', { method: 'POST', body: form });
  },

  documents: () =>
    request<
      Array<{
        id: string;
        filename: string;
        chunk_count: number;
        indexed_moss: boolean;
        status: string;
      }>
    >('/ingest/documents'),

  voiceToken: () => request<VoiceTokenResponse>('/voice/token'),
};
