'use client';

import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, FileText, Loader2, Upload } from 'lucide-react';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { api } from '@/lib/api';
import type { IngestResponse } from '@/lib/types';

/**
 * Corpus management: upload a document or paste text into the retrieval index.
 *
 * The Moss indexing status is reported explicitly per document. If Moss is not
 * configured, or indexing into it failed, that is stated here rather than left
 * implicit — otherwise a FAISS-only corpus looks identical to a Moss-backed one
 * until a query silently falls back.
 */
export function IngestPanel() {
  const [documents, setDocuments] = useState<
    Array<{ id: string; filename: string; chunk_count: number; indexed_moss: boolean }>
  >([]);
  const [text, setText] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function refresh() {
    try {
      setDocuments(await api.documents());
    } catch {
      // The panel is informational; a failed listing must not break the page.
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function report(result: IngestResponse) {
    const moss =
      result.moss_status === 'not_configured'
        ? 'Moss not configured — indexed into FAISS only.'
        : result.moss_status === 'failed'
          ? 'Moss indexing failed; FAISS only.'
          : `Indexed into Moss (${result.indexed_moss} docs).`;
    setMessage(`${result.filename}: ${result.chunk_count} chunks. ${moss}`);
    refresh();
  }

  async function submitText() {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      report(
        await api.ingestText({
          name: name.trim() || 'pasted-document.txt',
          text: text.trim(),
        }),
      );
      setText('');
      setName('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function submitFile(file: File) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      report(await api.ingestFile(file));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  }

  return (
    <Card>
      <CardHeader
        title="Document corpus"
        subtitle="Retrieval can only find what has been ingested."
        icon={FileText}
      />
      <CardBody className="space-y-3">
        <input
          ref={fileInput}
          type="file"
          accept=".txt,.md,.pdf"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) submitFile(file);
          }}
        />
        <button
          onClick={() => fileInput.current?.click()}
          disabled={busy}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-border-strong px-3 py-2.5 text-sm text-muted transition-colors hover:border-accent/50 hover:text-accent disabled:opacity-40"
        >
          {busy ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <Upload size={15} />
          )}
          Upload .txt, .md or .pdf
        </button>

        <div className="space-y-2 border-t border-border pt-3">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Document name"
            className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-faint focus:border-accent focus:outline-none"
          />
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={4}
            placeholder="…or paste text directly, e.g. &quot;Refunds are available within 7 days.&quot;"
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs text-foreground placeholder:text-faint focus:border-accent focus:outline-none"
          />
          <button
            onClick={submitText}
            disabled={busy || !text.trim()}
            className="w-full rounded-lg bg-surface-raised px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-border disabled:opacity-40"
          >
            Ingest text
          </button>
        </div>

        {message && (
          <p className="flex items-start gap-1.5 rounded-lg border border-reliable/30 bg-reliable-soft px-2.5 py-2 text-xs leading-relaxed text-reliable">
            <CheckCircle2 size={12} className="mt-0.5 shrink-0" />
            {message}
          </p>
        )}
        {error && (
          <p className="rounded-lg border border-failed/30 bg-failed-soft px-2.5 py-2 text-xs leading-relaxed text-failed">
            {error}
          </p>
        )}

        {documents.length > 0 && (
          <ul className="space-y-1 border-t border-border pt-3">
            {documents.slice(0, 8).map((document) => (
              <li
                key={document.id}
                className="flex items-center justify-between gap-2 text-xs"
              >
                <span className="truncate text-muted">{document.filename}</span>
                <span className="shrink-0 font-mono text-[10px] text-faint">
                  {document.chunk_count} chunks
                  {document.indexed_moss ? ' · moss' : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
