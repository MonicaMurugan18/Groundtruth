/**
 * Types mirroring the backend Pydantic schemas in `backend/app/schemas/`.
 *
 * Kept deliberately explicit rather than generated, so that a breaking backend
 * change surfaces as a TypeScript error rather than as a silently blank panel.
 *
 * Note `MetricScore.value` is `number | null`. A null value means the metric
 * could not be computed, which is NOT the same as a score of zero and must
 * never be rendered as 0%.
 */

export type ReliabilityStatus = 'reliable' | 'needs_review' | 'failed';
export type GuardrailStatus = 'pass' | 'review' | 'block';
export type ContextValidationStatus =
  | 'relevant'
  | 'insufficient'
  | 'irrelevant'
  | 'empty';
export type MetricStatus = 'ok' | 'unavailable' | 'error' | 'not_applicable';
export type SourceChannel = 'text' | 'voice';
export type RetrievalBackend = 'moss' | 'faiss' | 'none';

export interface MetricScore {
  value: number | null;
  status: MetricStatus;
  detail: string | null;
}

export interface RetrievedChunk {
  text: string;
  score: number | null;
  source: string | null;
  chunk_id: string | null;
  metadata: Record<string, unknown>;
}

export interface ContextValidation {
  status: ContextValidationStatus;
  reason: string;
  chunks_retrieved: number;
  max_similarity: number | null;
  mean_similarity: number | null;
}

export interface GuardrailResult {
  status: GuardrailStatus;
  reason: string;
  triggered: string[];
  stage: string;
}

/**
 * Ground-truth comparison. Distinct from faithfulness: this is the only field
 * that speaks to whether the answer is actually true.
 */
export interface FactualVerification {
  status: MetricStatus;
  correct: boolean | null;
  score: number | null;
  reason: string;
}

export interface LatencyBreakdown {
  retrieval_ms: number | null;
  llm_ms: number | null;
  guardrail_ms: number | null;
  evaluation_ms: number | null;
  context_validation_ms: number | null;
  total_ms: number;
  /** Moss reports its own search duration when it served the query. */
  moss_engine_ms?: number | null;
  [key: string]: number | null | undefined;
}

export interface EvaluationResponse {
  evaluation_id: string;
  created_at: string;
  channel: SourceChannel;

  query: string;
  contexts: RetrievedChunk[];
  answer: string;

  faithfulness: MetricScore;
  answer_relevance: MetricScore;
  context_precision: MetricScore;

  context_validation: ContextValidation;
  guardrail: GuardrailResult;
  factual_verification: FactualVerification;

  status: ReliabilityStatus;
  explanation: string;
  supported: boolean | null;

  retrieval_backend: RetrievalBackend;
  latency: LatencyBreakdown;
  warnings: string[];
}

export interface TraceSummary {
  evaluation_id: string;
  created_at: string;
  query: string;
  status: ReliabilityStatus;
  channel: SourceChannel;
  faithfulness: number | null;
  answer_relevance: number | null;
  guardrail_status: GuardrailStatus;
  total_ms: number | null;
}

export interface DashboardStats {
  total_evaluations: number;
  reliable_count: number;
  needs_review_count: number;
  failed_count: number;
  guardrail_violations: number;
  avg_faithfulness: number | null;
  avg_relevance: number | null;
  avg_context_precision: number | null;
  avg_latency_ms: number | null;
  voice_evaluations: number;
  recent: TraceSummary[];
}

export interface TraceListResponse {
  items: TraceSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ComponentStatus {
  name: string;
  configured: boolean;
  detail: string;
}

export interface CapabilitiesResponse {
  components: ComponentStatus[];
  degraded: string[];
}

export interface IngestResponse {
  document_id: string;
  filename: string;
  chunk_count: number;
  indexed_faiss: number;
  indexed_moss: number;
  moss_status: string;
  warnings: string[];
}

export interface VoiceTokenResponse {
  server_url: string;
  token: string;
  room: string;
  identity: string;
  agent_name: string;
}
