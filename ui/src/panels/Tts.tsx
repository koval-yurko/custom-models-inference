import { useEffect, useRef, useState } from "react";
import { call, curlFor, errorText } from "../api";
import { PcmPlayer, wavFromPcm } from "../audio";
import { Curl, Status, Timings, type Timing } from "../components";
import type { ModelConfig } from "../config";

// OpenAI-compatible TTS: POST /v1/audio/speech, GET /v1/audio/voices (features.voices).
// Stream mode always asks for "pcm": the browser can play raw PCM chunks at once (Web Audio) in every browser.

const LONG_TEXT = Array.from({ length: 40 }, (_, i) => `This is sentence number ${i + 1} of a long text to test streaming.`).join(" ");
const MIME: Record<string, string> = { mp3: "audio/mpeg", wav: "audio/wav", opus: "audio/ogg", flac: "audio/flac", aac: "audio/aac" };

/** Kokoro returns voice objects ({id, name, ...}); other servers return plain strings. */
export function voiceIds(voices: unknown): string[] {
  if (!Array.isArray(voices)) return [];
  return voices.map((v) => (typeof v === "string" ? v : (v?.id ?? v?.name))).filter((v): v is string => typeof v === "string");
}

export default function Tts({ model }: { model: ModelConfig }) {
  const f = model.features as { stream?: boolean; voices?: boolean; default_voice?: string; formats?: string[]; sample_rate?: number };
  const sampleRate = f.sample_rate ?? 24000;
  const [text, setText] = useState("Hello from the test UI.");
  const [voices, setVoices] = useState<string[]>(f.default_voice ? [f.default_voice] : []);
  const [voice, setVoice] = useState(f.default_voice ?? "");
  const [speed, setSpeed] = useState(1);
  const [format, setFormat] = useState(f.formats?.[0] ?? "mp3");
  const [stream, setStream] = useState(false);
  const [busy, setBusy] = useState(false);
  const [t, setT] = useState<Timing>({});
  const [error, setError] = useState<string>();
  const [audio, setAudio] = useState<{ url: string; name: string }>();
  const [curl, setCurl] = useState("");
  const abort = useRef<AbortController>(null);
  const player = useRef<PcmPlayer>(null);

  const loadVoices = async () => {
    try {
      const res = await call(model, "/v1/audio/voices", { method: "GET" });
      if (!res.ok) return setError(`Voices: ${await errorText(res)}`);
      const list = voiceIds((await res.json()).voices);
      if (list.length) setVoices(list);
      setError(undefined);
    } catch (e) {
      setError(`Voices: ${e}`);
    }
  };
  useEffect(() => {
    if (f.voices) void loadVoices();
  }, [model.base_url]); // eslint-disable-line react-hooks/exhaustive-deps

  const generate = async () => {
    stop();
    // The player is made here, in the click handler: browsers start audio only after a user gesture.
    if (stream) player.current = new PcmPlayer(sampleRate);
    abort.current = new AbortController();
    const fmt = stream ? "pcm" : format;
    const body = { model: model.model, input: text, voice, speed, response_format: fmt, stream };
    setCurl(curlFor(model, "/v1/audio/speech", body));
    setError(undefined);
    setAudio(undefined);
    setBusy(true);
    const t0 = performance.now();
    const timing: Timing = {};
    try {
      const res = await call(model, "/v1/audio/speech", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: abort.current.signal,
      });
      timing.status = res.status;
      if (!res.ok || !res.body) throw new Error(await errorText(res));
      const reader = res.body.getReader();
      const chunks: Uint8Array[] = [];
      timing.bytes = 0;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        timing.firstMs ??= performance.now() - t0;
        timing.bytes += value.byteLength;
        chunks.push(value);
        player.current?.push(value);
        setT({ ...timing });
      }
      timing.totalMs = performance.now() - t0;
      const blob = fmt === "pcm" ? wavFromPcm(chunks, sampleRate) : new Blob(chunks as BlobPart[], { type: MIME[fmt] ?? "application/octet-stream" });
      setAudio({ url: URL.createObjectURL(blob), name: `${model.id}-${Date.now()}.${fmt === "pcm" ? "wav" : fmt}` });
    } catch (e) {
      if (!abort.current?.signal.aborted) setError(String(e));
    } finally {
      setT({ ...timing });
      setBusy(false);
    }
  };

  const stop = () => {
    abort.current?.abort();
    player.current?.stop();
    player.current = null;
  };

  return (
    <section className="panel">
      <div className="form">
        <label>
          Text
          <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <button className="link" onClick={() => setText(LONG_TEXT)}>
          Fill a long text (about 3 min of audio, to see streaming)
        </button>
        <div className="row">
          <label>
            Voice
            <select value={voice} onChange={(e) => setVoice(e.target.value)}>
              {voices.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          {f.voices && <button onClick={loadVoices}>Reload voices</button>}
          <label>
            Speed
            <input type="number" step="0.1" min="0.25" max="4" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} />
          </label>
          <label>
            Format
            <select value={stream ? "pcm" : format} disabled={stream} onChange={(e) => setFormat(e.target.value)}>
              {(f.formats ?? ["mp3"]).map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
        </div>
        <fieldset className="row">
          <label className="inline">
            <input type="radio" checked={!stream} onChange={() => setStream(false)} /> Wait for the full file
          </label>
          <label className="inline">
            <input type="radio" checked={stream} disabled={!f.stream} onChange={() => setStream(true)} /> Stream and play at once (PCM)
          </label>
        </fieldset>
        <div className="row">
          <button className="primary" disabled={busy || !text} onClick={generate}>
            Generate
          </button>
          <button onClick={stop}>Stop</button>
        </div>
      </div>
      <div className="result">
        <Status error={error} />
        {busy && <p className="info">{stream ? "Playing while it streams…" : "Waiting for the audio…"}</p>}
        {audio && (
          <>
            {/* After a stream, the audio has already played. The player is for a replay. */}
            <audio controls autoPlay={!stream} src={audio.url} />
            <a className="button" href={audio.url} download={audio.name}>
              Download {audio.name.split(".").pop()}
            </a>
          </>
        )}
        <Timings t={t} firstLabel="First byte" />
        <Curl text={curl} />
      </div>
    </section>
  );
}
