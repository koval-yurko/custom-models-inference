import { useRef, useState } from "react";
import { call, curlFor, errorText } from "../api";
import { Curl, Status, Timings, type Timing } from "../components";
import type { ModelConfig } from "../config";
import { readSse } from "../sse";

// OpenAI-compatible chat: POST /v1/chat/completions, SSE when stream is on (features.stream).

type Msg = { role: "system" | "user" | "assistant"; content: string };

export default function Llm({ model }: { model: ModelConfig }) {
  const f = model.features as { stream?: boolean; max_tokens?: number };
  const [system, setSystem] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [stream, setStream] = useState(!!f.stream);
  const [maxTokens, setMaxTokens] = useState(f.max_tokens ?? 1024);
  const [temperature, setTemperature] = useState(0.7);
  const [busy, setBusy] = useState(false);
  const [t, setT] = useState<Timing>({});
  const [error, setError] = useState<string>();
  const [retry, setRetry] = useState<number>();
  const [curl, setCurl] = useState("");
  const abort = useRef<AbortController>(null);

  const send = async () => {
    if (!input.trim() || busy) return;
    const history: Msg[] = [...msgs, { role: "user", content: input }];
    setMsgs([...history, { role: "assistant", content: "" }]);
    setInput("");
    const appendAnswer = (s: string) =>
      setMsgs((m) => [...m.slice(0, -1), { role: "assistant", content: m[m.length - 1].content + s }]);

    const body = {
      model: model.model,
      messages: system ? [{ role: "system", content: system }, ...history] : history,
      max_tokens: maxTokens,
      temperature,
      stream,
      ...(stream && { stream_options: { include_usage: true } }),
    };
    setCurl(curlFor(model, "/v1/chat/completions", body));
    setError(undefined);
    setBusy(true);
    abort.current = new AbortController();
    const timing: Timing = {};
    let t0 = performance.now();
    try {
      const res = await call(
        model,
        "/v1/chat/completions",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: abort.current.signal },
        (n) => {
          setRetry(n);
          timing.retries = n;
          t0 = performance.now(); // time the call that answers, not the wait for the cold start
        },
      );
      setRetry(undefined);
      timing.status = res.status;
      if (!res.ok || !res.body) throw new Error(await errorText(res));
      if (stream) {
        for await (const data of readSse(res.body)) {
          const j = JSON.parse(data);
          const delta: string | undefined = j.choices?.[0]?.delta?.content;
          if (delta) {
            timing.firstMs ??= performance.now() - t0;
            appendAnswer(delta);
          }
          if (j.usage) timing.tokens = j.usage.completion_tokens;
          setT({ ...timing });
        }
      } else {
        const j = await res.json();
        timing.firstMs = performance.now() - t0;
        timing.tokens = j.usage?.completion_tokens;
        appendAnswer(j.choices?.[0]?.message?.content ?? JSON.stringify(j));
      }
      timing.totalMs = performance.now() - t0;
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
      <div className="form chat">
        <label>
          System prompt (optional)
          <textarea rows={2} value={system} onChange={(e) => setSystem(e.target.value)} />
        </label>
        <div className="messages">
          {msgs.length === 0 && <p className="muted">No messages yet.</p>}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <b>{m.role === "user" ? "You" : model.title}</b>
              <div>{m.content || (busy && i === msgs.length - 1 ? "…" : "")}</div>
            </div>
          ))}
        </div>
        <textarea
          rows={3}
          placeholder="Message… (Enter sends, Shift+Enter is a new line)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <div className="row">
          <button className="primary" disabled={busy || !input.trim()} onClick={send}>
            Send
          </button>
          <button onClick={() => abort.current?.abort()}>Stop</button>
          <button disabled={busy} onClick={() => (setMsgs([]), setT({}), setCurl(""))}>
            New chat
          </button>
        </div>
      </div>
      <div className="result">
        <div className="row">
          <label className="inline">
            <input type="checkbox" checked={stream} disabled={!f.stream} onChange={(e) => setStream(e.target.checked)} /> Stream (SSE)
          </label>
          <label>
            max_tokens
            <input type="number" min="1" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} />
          </label>
          <label>
            temperature
            <input type="number" step="0.1" min="0" max="2" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
          </label>
        </div>
        <Status error={error} retry={retry} />
        <Timings t={t} firstLabel="First token" />
        <Curl text={curl} />
      </div>
    </section>
  );
}
