import { getApiKey, type ModelConfig } from "./config";

const MAX_WAIT_MS = 30 * 60_000; // 30 min, the same as the README loop
const LONG_MS = 30_000; // a failure after this long is a gateway time limit, not a wrong key

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => (clearTimeout(t), reject(signal.reason)), { once: true });
  });
}

/** cold_start rules that mean "429 at 0 replicas, retry": retry-429 (Vertex AI, Runpod) and its old name vertex-429. hold (a platform that keeps the request open) waits in it. */
export const retriesOn429 = (coldStart: unknown) => coldStart === "retry-429" || coldStart === "vertex-429";
const scalesToZero = (coldStart: unknown) => retriesOn429(coldStart) || coldStart === "hold";

export type RetryReason = "429" | "timeout";

/** When to send the request again. status undefined = fetch failed (API Gateway sends its 504 without CORS headers).
 * A timeout means the gateway stopped waiting while the replica still starts. Only panels with a repeatable request
 * (LLM chat) allow it: a second STT POST would start a second run. */
export function retryPlan(status: number | undefined, elapsedMs: number, coldStart: unknown, retryTimeouts: boolean): { reason: RetryReason; waitMs: number } | null {
  if (status === 429 && retriesOn429(coldStart)) return { reason: "429", waitMs: 30_000 };
  const timedOut = status === undefined || status === 502 || status === 504;
  if (retryTimeouts && timedOut && elapsedMs >= LONG_MS && scalesToZero(coldStart)) return { reason: "timeout", waitMs: 2_000 };
  return null;
}

const clock = (ms: number) => `${Math.floor(ms / 60_000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

/** The progress line while a panel waits for the first answer byte. null: nothing to show yet. */
export function waitText(w: { elapsedMs: number; coldStart?: unknown; label?: string; attempt?: number; reason?: RetryReason }): string | null {
  if (w.elapsedMs < 3_000 && !w.attempt) return null;
  let s = `Waiting for ${w.label ?? "the model"}… ${clock(w.elapsedMs)}.`;
  if (w.reason === "429") s += ` The model is starting (HTTP 429): retry ${w.attempt}, every 30 s.`;
  else if (w.reason === "timeout") s += ` The gateway stopped after its time limit, but the replica is still starting: attempt ${(w.attempt ?? 0) + 1}.`;
  else if (scalesToZero(w.coldStart) && w.elapsedMs >= 10_000) s += " Probably a cold start: a replica starts, this takes about 3 to 10 minutes.";
  return `${s} Press Stop to cancel.`;
}

/** fetch through the gateway with the API key. Retries by retryPlan: a 429 at 0 replicas (Vertex AI, Runpod), and with
 * retryTimeouts a gateway timeout during a cold start. A fast network error is not retried: it means a wrong key, CORS or the URL. */
export async function call(
  model: ModelConfig,
  path: string,
  init: RequestInit & { signal?: AbortSignal },
  onRetry?: (attempt: number, reason: RetryReason) => void,
  opts: { retryTimeouts?: boolean } = {},
): Promise<Response> {
  const begin = Date.now();
  for (let attempt = 0; ; attempt++) {
    const sent = Date.now();
    let res: Response | undefined;
    let failure: unknown;
    try {
      res = await fetch(model.base_url + path, { ...init, headers: { ...init.headers, "x-api-key": getApiKey() } });
    } catch (e) {
      if (init.signal?.aborted) throw e;
      failure = e;
    }
    const plan = retryPlan(res?.status, Date.now() - sent, model.features.cold_start, !!opts.retryTimeouts);
    if (!plan || Date.now() - begin + plan.waitMs > MAX_WAIT_MS) {
      if (res) return res;
      // The browser hides the reason. The gateway rejects a wrong key (HTTP 400/401) without CORS headers,
      // so a wrong key looks the same as a CORS or network failure.
      const late = Date.now() - sent >= LONG_MS ? ` It failed after ${clock(Date.now() - sent)}: most likely the gateway time limit.` : "";
      throw new Error(`Request to ${path} failed. Most likely a wrong API key; else gateway CORS (OPTIONS), the URL or the network.${late} (${failure})`);
    }
    onRetry?.(attempt + 1, plan.reason);
    await sleep(plan.waitMs, init.signal);
  }
}

export async function errorText(res: Response) {
  return `HTTP ${res.status}: ${(await res.text()).slice(0, 1000)}`;
}

/** The same request as a curl command, for the terminal. The key stays out: it uses $KEY. */
export function curlFor(model: ModelConfig, path: string, body?: unknown) {
  const parts = [`curl -sS -N -X ${body ? "POST" : "GET"} "${model.base_url}${path}"`, `-H "x-api-key: $KEY"`];
  if (body) parts.push(`-H "Content-Type: application/json"`, `-d '${JSON.stringify(body).replace(/'/g, "'\\''")}'`);
  return parts.join(" \\\n  ");
}
