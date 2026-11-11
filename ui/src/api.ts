import { getApiKey, type ModelConfig } from "./config";

const RETRY_EVERY_MS = 30_000;
const MAX_RETRIES = 60; // 30 min, the same as the README loop

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => (clearTimeout(t), reject(signal.reason)), { once: true });
  });
}

/** fetch through the gateway with the API key. Vertex AI returns 429 at 0 replicas: retry while it starts. */
export async function call(
  model: ModelConfig,
  path: string,
  init: RequestInit & { signal?: AbortSignal },
  onRetry?: (attempt: number) => void,
): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    let res: Response;
    try {
      res = await fetch(model.base_url + path, { ...init, headers: { ...init.headers, "x-api-key": getApiKey() } });
    } catch (e) {
      if (init.signal?.aborted) throw e;
      // The browser hides the reason. The gateway rejects a wrong key (HTTP 400/401) without CORS headers,
      // so a wrong key looks the same as a CORS or network failure.
      throw new Error(`Request to ${path} failed. Most likely a wrong API key; else gateway CORS (OPTIONS), the URL or the network. (${e})`);
    }
    if (res.status !== 429 || model.features.cold_start !== "vertex-429" || attempt >= MAX_RETRIES) return res;
    onRetry?.(attempt + 1);
    await sleep(RETRY_EVERY_MS, init.signal);
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
