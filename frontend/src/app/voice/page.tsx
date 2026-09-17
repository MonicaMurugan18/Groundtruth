'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  BarVisualizer,
  LiveKitRoom,
  RoomAudioRenderer,
  StartAudio,
  useDataChannel,
  useVoiceAssistant,
  VoiceAssistantControlBar,
} from '@livekit/components-react';
import '@livekit/components-styles';
import { Loader2, Mic, Radio, TriangleAlert } from 'lucide-react';
import { PageHeader } from '@/components/AppShell';
import { Card, CardBody, CardHeader, EmptyState } from '@/components/ui/Card';
import { ReliabilityBadge } from '@/components/ui/StatusBadge';
import { api, ApiError } from '@/lib/api';
import type { EvaluationResponse, VoiceTokenResponse } from '@/lib/types';

/**
 * Voice evaluation via LiveKit.
 *
 * The browser only ever holds a short-lived, room-scoped token minted by the
 * backend — the LiveKit API secret never reaches the client.
 *
 * The voice agent publishes an evaluation summary on the `groundtruth_eval`
 * data topic after each turn, so the trust report appears live as the
 * conversation happens. Those turns are also persisted server-side and show up
 * on the dashboard labelled as voice.
 */
export default function VoicePage() {
  const [session, setSession] = useState<VoiceTokenResponse | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);

  // Probe configuration up front so the page can explain a missing credential
  // rather than failing at connect time.
  useEffect(() => {
    api
      .capabilities()
      .then((caps) => {
        const livekit = caps.components.find((c) => c.name === 'livekit');
        if (livekit && !livekit.configured) setUnavailable(livekit.detail);
      })
      .catch(() => {
        /* the shell already surfaces API connectivity problems */
      });
  }, []);

  async function connect() {
    setConnecting(true);
    setError(null);
    try {
      setSession(await api.voiceToken());
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      setConnecting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Voice evaluation"
        description="Speak to the agent over LiveKit. Each spoken turn runs through the same retrieval, guardrail and scoring pipeline as a typed query."
      />

      {unavailable ? (
        <Card>
          <EmptyState
            icon={Mic}
            title="LiveKit is not configured"
            description={`${unavailable} Add the LiveKit credentials to backend/.env and restart the API to enable voice evaluation.`}
          />
        </Card>
      ) : !session ? (
        <Card>
          <EmptyState
            icon={Mic}
            title="Start a voice session"
            description="Connecting requests a short-lived, room-scoped LiveKit token from the backend. Your microphone is only used while the session is open."
            action={
              <button
                onClick={connect}
                disabled={connecting}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
              >
                {connecting ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Mic size={15} />
                )}
                Connect
              </button>
            }
          />
          {error && (
            <p className="mx-5 mb-5 rounded-lg border border-failed/30 bg-failed-soft px-3 py-2 text-xs leading-relaxed text-failed">
              {error}
            </p>
          )}
        </Card>
      ) : (
        <LiveKitRoom
          serverUrl={session.server_url}
          token={session.token}
          connect
          audio
          video={false}
          onDisconnected={() => setSession(null)}
          data-lk-theme="default"
        >
          <VoiceSession room={session.room} />
          <RoomAudioRenderer />
          <StartAudio label="Enable audio" />
        </LiveKitRoom>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

const AGENT_STATE_LABEL: Record<string, string> = {
  disconnected: 'Waiting for the agent to join',
  connecting: 'Agent connecting',
  initializing: 'Agent starting up',
  listening: 'Listening',
  thinking: 'Retrieving and evaluating',
  speaking: 'Speaking',
};

function VoiceSession({ room }: { room: string }) {
  const { state, audioTrack, agent } = useVoiceAssistant();
  const [turns, setTurns] = useState<EvaluationResponse[]>([]);

  // The agent publishes each evaluated turn on this topic. The payload is the
  // same EvaluationResponse the REST API returns.
  const onMessage = useCallback((message: { payload: Uint8Array }) => {
    try {
      const decoded = new TextDecoder().decode(message.payload);
      const parsed = JSON.parse(decoded) as EvaluationResponse;
      if (parsed?.evaluation_id) {
        setTurns((previous) => [parsed, ...previous].slice(0, 20));
      }
    } catch {
      // A malformed frame must not take the page down.
    }
  }, []);

  useDataChannel('groundtruth_eval', onMessage);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader
          title="Session"
          subtitle={`Room ${room}`}
          icon={Radio}
          action={
            <span className="flex items-center gap-1.5 text-xs text-muted">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  state === 'listening' || state === 'speaking'
                    ? 'bg-reliable'
                    : 'bg-review'
                }`}
              />
              {AGENT_STATE_LABEL[state] ?? state}
            </span>
          }
        />
        <CardBody className="space-y-4">
          <div className="flex h-24 items-center justify-center rounded-lg border border-border bg-surface-raised">
            {audioTrack ? (
              <BarVisualizer
                state={state}
                barCount={7}
                trackRef={audioTrack}
                className="h-16"
              />
            ) : (
              <p className="text-xs text-faint">
                No agent audio track yet
              </p>
            )}
          </div>

          <VoiceAssistantControlBar />

          {!agent && (
            <p className="flex items-start gap-1.5 rounded-lg border border-review/30 bg-review-soft px-3 py-2 text-xs leading-relaxed text-review">
              <TriangleAlert size={12} className="mt-0.5 shrink-0" />
              No agent has joined this room. Start the voice agent with{' '}
              <code className="font-mono">python agent/agent.py dev</code>, then
              reconnect.
            </p>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Evaluated turns"
          subtitle="Each spoken turn, scored as it happens."
          icon={Mic}
        />
        <CardBody className="px-0 py-0">
          {turns.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-faint">
              Ask the agent a question. Its answer will be evaluated and appear
              here, and in the dashboard history.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {turns.map((turn) => (
                <li key={turn.evaluation_id} className="px-5 py-3">
                  <div className="mb-1.5 flex items-center gap-2">
                    <ReliabilityBadge status={turn.status} size="sm" />
                    <span className="font-mono text-[11px] text-faint">
                      {turn.faithfulness.value === null
                        ? 'faithfulness —'
                        : `faithfulness ${(turn.faithfulness.value * 100).toFixed(0)}%`}
                      {' · '}
                      {turn.latency.total_ms.toFixed(0)}ms
                    </span>
                  </div>
                  <p className="text-sm text-foreground">{turn.query}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted">
                    {turn.answer}
                  </p>
                  <p className="mt-1.5 text-xs leading-relaxed text-faint">
                    {turn.explanation}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
