import { useRef, useState } from "react";
import { call, curlFor, errorText } from "../api";
import { Curl, Status, Timings, type Timing } from "../components";
import type { ModelConfig } from "../config";

// Own FastAPI routes of LLM-B (deployments/llm-b-qwen35-9b-fastapi/image/app.py), one JSON answer each:
//   POST /extract  {text, schema?, max_tokens} -> {data}   (JSON that matches the schema)
//   POST /generate {prompt, max_tokens, temperature} -> {text}

type Route = "/extract" | "/generate";

const SAMPLE_TEXT = "Ada Lovelace met Charles Babbage in London on 5 June 1833. Both later worked with the Royal Society.";

/** Empty text means "use the default schema of app.py". Returns an error text for invalid JSON. */
export function parseSchema(text: string): { schema?: object; error?: string } {
  if (!text.trim()) return {};
  try {
    const v = JSON.parse(text);
    if (typeof v !== "object" || v === null || Array.isArray(v)) return { error: "The schema must be a JSON object." };
    return { schema: v };
  } catch (e) {
    return { error: `The schema is not valid JSON: ${(e as Error).message}` };
  }
}

export default function LlmRoutes({ model }: { model: ModelConfig }) {
  const f = model.features as { max_tokens?: number; routes?: string[] };
  const routes = (f.routes ?? ["/extract", "/generate"]) as Route[];
  const [route, setRoute] = useState<Route>(routes[0]);
  const [text, setText] = useState(SAMPLE_TEXT);
  const [schemaText, setSchemaText] = useState("");
  const [prompt, setPrompt] = useState("Say hello in 5 words.");
  const [maxTokens, setMaxTokens] = useState(f.max_tokens ?? 512);
  const [temperature, setTemperature] = useState(0.7);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [t, setT] = useState<Timing>({});
  const [error, setError] = useState<string>();
  const [retry, setRetry] = useState<number>();
  const [curl, setCurl] = useState("");
  const abort = useRef<AbortController>(null);

  const send = async () => {
    if (busy) return;
    let body: object;
    if (route === "/extract") {
      const { schema, error: schemaError } = parseSchema(schemaText);
      if (schemaError) return setError(schemaError);
      body = { text, max_tokens: maxTokens, ...(schema && { schema }) };
    } else {
      body = { prompt, max_tokens: maxTokens, temperature };
    }
    setCurl(curlFor(model, route, body));
    setError(undefined);
    setAnswer("");
    setBusy(true);
    abort.current = new AbortController();
    const timing: Timing = {};
    let t0 = performance.now();
    try {
      const res = await call(
        model,
        route,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: abort.current.signal },
        (n) => {
          setRetry(n);
          timing.retries = n;
          t0 = performance.now(); // time the call that answers, not the wait for the cold start
        },
      );
      setRetry(undefined);
      timing.status = res.status;
      if (!res.ok) throw new Error(await errorText(res));
      const j = await res.json();
      timing.totalMs = timing.firstMs = performance.now() - t0;
      setAnswer(route === "/extract" ? JSON.stringify(j.data, null, 2) : String(j.text ?? JSON.stringify(j)));
    } catch (e) {
      if (!abort.current?.signal.aborted) setError(String(e));
    } finally {
      setRetry(undefined);
      setT({ ...timing });
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="form">
        <div className="row">
          {routes.map((r) => (
            <label key={r} className="inline">
              <input type="radio" name={`route-${model.id}`} checked={route === r} onChange={() => (setRoute(r), setAnswer(""), setError(undefined), setT({}), setCurl(""))} /> {r}
            </label>
          ))}
        </div>
        {route === "/extract" ? (
          <>
            <label>
              Text
              <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} />
            </label>
            <label>
              JSON schema (optional; empty = people, organizations, places, dates)
              <textarea rows={5} placeholder='{"type":"object","properties":{...}}' value={schemaText} onChange={(e) => setSchemaText(e.target.value)} />
            </label>
          </>
        ) : (
          <label>
            Prompt
            <textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </label>
        )}
        <div className="row">
          <label>
            max_tokens
            <input type="number" min="1" max="4096" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} />
          </label>
          {route === "/generate" && (
            <label>
              temperature
              <input type="number" step="0.1" min="0" max="2" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
            </label>
          )}
        </div>
        <div className="row">
          <button className="primary" disabled={busy || !(route === "/extract" ? text : prompt).trim()} onClick={send}>
            Send
          </button>
          <button onClick={() => abort.current?.abort()}>Stop</button>
        </div>
      </div>
      <div className="result">
        <Status error={error} retry={retry} />
        {answer && <pre className="answer">{answer}</pre>}
        <Timings t={t} firstLabel="Answer" />
        <Curl text={curl} />
      </div>
    </section>
  );
}
