// Parts that every panel uses.

export interface Timing {
  status?: number;
  firstMs?: number; // first byte (TTS) or first token (LLM)
  totalMs?: number;
  bytes?: number;
  tokens?: number;
  retries?: number;
}

const s = (ms?: number) => (ms === undefined ? "–" : `${(ms / 1000).toFixed(2)} s`);

export function Timings({ t, firstLabel }: { t: Timing; firstLabel: string }) {
  const genMs = t.totalMs !== undefined && t.firstMs !== undefined ? t.totalMs - t.firstMs : undefined;
  const tps = t.tokens && genMs ? (t.tokens / (genMs / 1000)).toFixed(1) : undefined;
  return (
    <dl className="timings">
      <dt>HTTP</dt>
      <dd>{t.status ?? "–"}</dd>
      <dt>{firstLabel}</dt>
      <dd>{s(t.firstMs)}</dd>
      <dt>Total</dt>
      <dd>{s(t.totalMs)}</dd>
      {t.bytes !== undefined && (
        <>
          <dt>Size</dt>
          <dd>{(t.bytes / 1024).toFixed(0)} KB</dd>
        </>
      )}
      {t.tokens !== undefined && (
        <>
          <dt>Tokens</dt>
          <dd>
            {t.tokens}
            {tps && ` (${tps} tok/s)`}
          </dd>
        </>
      )}
      {!!t.retries && (
        <>
          <dt>Cold-start retries</dt>
          <dd>{t.retries}</dd>
        </>
      )}
    </dl>
  );
}

export function Curl({ text }: { text: string }) {
  if (!text) return null;
  return (
    <details className="curl">
      <summary>Request as curl</summary>
      <pre>{text}</pre>
      <button onClick={() => navigator.clipboard?.writeText(text)}>Copy</button>
    </details>
  );
}

export function Status({ error, retry }: { error?: string; retry?: number }) {
  if (error) return <p className="error">{error}</p>;
  if (retry) return <p className="info">Model is starting (HTTP 429)… retry {retry}/60, every 30 s. Press Stop to cancel.</p>;
  return null;
}
