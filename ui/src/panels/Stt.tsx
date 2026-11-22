import { useEffect, useRef, useState } from "react";
import { call, curlFor, errorText } from "../api";
import { Curl, Status, Timings, type Timing } from "../components";
import { parseHash, type ModelConfig } from "../config";

// STT-A with stored files and transcript history (spec: docs/specs/2026-11-21-stt-a-design.md).
// Every file goes through POST /v1beta/uploads (signed PUT). Each run of POST /v1beta/files/<id>/transcribe is saved
// as a version by the files service. 2 ticked versions show side by side.

export interface WordInfo {
  type: string;
  text: string;
  speaker?: string;
  start_offset: string;
  end_offset: string;
}
interface FileRow { id: string; name: string; mime_type: string; size_bytes: number; created: string; versions: number; latest: string | null }
interface Summary { id: string; created: string; label: string; image_tag: string; run_seconds: number; settings: { language_codes: string[]; diarization: boolean }; text_chars: number; speakers: number }
type Names = Record<string, string>; // per version: {"spk_1": "Alice"} (PUT .../versions/<id>/names)
interface Version extends Omit<Summary, "text_chars" | "speakers"> { names?: Names; response: { output_text?: string; steps?: { content?: { annotations?: WordInfo[] }[] }[] } }

const LANGS = ["zh", "en", "yue", "ar", "de", "fr", "es", "pt", "id", "it", "ko", "ru", "th", "vi", "ja", "tr", "hi", "ms", "nl", "sv", "da", "fi", "pl", "cs", "fil", "fa", "el", "hu", "mk", "ro"];
// The files service accepts only these types. Browsers give other names (audio/x-m4a) or none.
const MIME: Record<string, string> = { mp3: "audio/mpeg", wav: "audio/wav", m4a: "audio/m4a", ogg: "audio/ogg", flac: "audio/flac", webm: "audio/webm", aac: "audio/aac", opus: "audio/opus", aiff: "audio/aiff", aif: "audio/aiff" };
const COLORS = ["#2563eb", "#d97706", "#059669", "#dc2626", "#7c3aed", "#db2777", "#0891b2", "#65a30d"];
const JSON_HDR = { "Content-Type": "application/json" };

/** Consecutive words of 1 speaker -> 1 line, with the start of its first word and the end of its last word. */
export function groupTurns(annotations: WordInfo[]): { speaker: string; text: string; start: string; end: string }[] {
  const out: { speaker: string; text: string; start: string; end: string }[] = [];
  for (const w of annotations) {
    const speaker = w.speaker ?? "";
    const last = out.at(-1);
    if (last && last.speaker === speaker) (last.text += ` ${w.text}`), (last.end = w.end_offset);
    else out.push({ speaker, text: w.text, start: w.start_offset, end: w.end_offset });
  }
  return out;
}

/** API Gateway sends its 504 without CORS headers, so the browser hides it: fetch fails with no status. */
export const gatewayTimedOut = (status: number | undefined, elapsedMs: number) => status === 504 || (status === undefined && elapsedMs >= 290_000);
const TIMEOUT_MSG = "The gateway stopped waiting after 300 s. The run can still finish. Press Refresh in a few minutes.";

/** "8.958s" (Gemini offset) -> "00:00:08". */
export function clock(offset: string): string {
  const t = Math.floor(parseFloat(offset));
  return [t / 3600, (t / 60) % 60, t % 60].map((n) => String(Math.floor(n)).padStart(2, "0")).join(":");
}

/** The given name of a speaker label, else the label. Words without a speaker show as "text". */
export const speakerName = (names: Names | undefined, speaker: string) => names?.[speaker] || speaker || "text";

/** Draft names -> the PUT body: trimmed, empty names left out (the label shows again). */
export const namesBody = (draft: Names): Names => Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v));

export const speakerCount = (annotations: WordInfo[]) => new Set(annotations.map((w) => w.speaker).filter(Boolean)).size;

const mimeOf = (f: File) => MIME[f.name.split(".").pop()?.toLowerCase() ?? ""] ?? (f.type || "audio/wav");
const words = (v: Version) => v.response.steps?.[0]?.content?.[0]?.annotations ?? [];
const when = (iso: string) => iso.replace("T", " ").replace(/:\d\dZ$/, "");
const vtime = (id: string) => `${id.slice(0, 4)}-${id.slice(4, 6)}-${id.slice(6, 8)} ${id.slice(9, 11)}:${id.slice(11, 13)}`;

interface TranscriptProps {
  v: Version;
  playing?: number; // index of the turn that plays now
  onPlay: (turn: number, start: number, end: number) => void;
  onNames: (names: Names) => Promise<void>;
}

function Transcript({ v, playing, onPlay, onNames }: TranscriptProps) {
  const groups = groupTurns(words(v));
  const speakers = [...new Set(groups.map((g) => g.speaker))];
  const labels = speakers.filter(Boolean);
  const [draft, setDraft] = useState<Names>(v.names ?? {});
  const [saving, setSaving] = useState(false);
  useEffect(() => setDraft(v.names ?? {}), [v.names]);
  const color = (spk: string) => COLORS[speakers.indexOf(spk) % COLORS.length];
  const save = () => (setSaving(true), onNames(namesBody(draft)).finally(() => setSaving(false)));
  return (
    <div className="transcript">
      <p className="muted">
        {vtime(v.id)} · image {v.image_tag} · {v.label || "no label"}
      </p>
      {labels.length > 0 && (
        <div className="row speakers">
          {labels.map((spk) => (
            <label key={spk} style={{ color: color(spk) }}>
              {spk}
              <input aria-label={`Name of ${spk}`} value={draft[spk] ?? ""} maxLength={40} placeholder={spk} onChange={(e) => setDraft({ ...draft, [spk]: e.target.value })} />
            </label>
          ))}
          <button disabled={saving} onClick={() => void save()}>
            Save names
          </button>
        </div>
      )}
      {groups.length === 0 && <p>{v.response.output_text || "(no speech)"}</p>}
      {groups.map((g, i) => (
        <p key={i} className={playing === i ? "turn playing" : "turn"}>
          <button className="play" aria-label={`${playing === i ? "Stop" : "Play"} turn ${i + 1}`} onClick={() => onPlay(i, parseFloat(g.start), parseFloat(g.end))}>
            {playing === i ? "■" : "▶"}
          </button>{" "}
          <span style={{ color: color(g.speaker), fontWeight: 600 }}>
            {speakerName(v.names, g.speaker)} {clock(g.start)} – {clock(g.end)}
          </span>{" "}
          {g.text}
        </p>
      ))}
    </div>
  );
}

export default function Stt({ model }: { model: ModelConfig }) {
  const [files, setFiles] = useState<FileRow[]>([]);
  const [fileId, setFileId] = useState<string | undefined>(() => (parseHash(location.hash).tab === model.id ? parseHash(location.hash).file : undefined));
  const [detail, setDetail] = useState<{ file: FileRow; versions: Summary[] }>();
  const [ticked, setTicked] = useState<string[]>([]);
  const [full, setFull] = useState<Record<string, Version>>({});
  const [lang, setLang] = useState("");
  const [diarize, setDiarize] = useState(true);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState("");
  const [t, setT] = useState<Timing>({});
  const [retry, setRetry] = useState<number>();
  const [error, setError] = useState<string>();
  const [curl, setCurl] = useState("");
  const abort = useRef<AbortController>(null);
  // 1 <audio> for all turns. The signed GET URL lasts 15 minutes, so it is fetched again after 10 minutes.
  const audio = useRef<HTMLAudioElement>(null);
  const audioSrc = useRef<{ file: string; at: number }>(null);
  const stopAt = useRef(0);
  const [playing, setPlaying] = useState<{ version: string; turn: number }>();
  const current = useRef(fileId); // the selected file: a late answer for another file must not show
  current.current = fileId;

  const get = async <T,>(path: string): Promise<T> => {
    const res = await call(model, path, { method: "GET" });
    if (!res.ok) throw new Error(await errorText(res));
    return res.json();
  };
  const loadFiles = () => get<{ files: FileRow[] }>("/v1beta/files").then((d) => setFiles(d.files), (e) => setError(String(e)));
  const loadDetail = (id: string) =>
    get<{ file: FileRow; versions: Summary[] }>(`/v1beta/files/${id}`).then(
      (d) => {
        if (current.current !== id) return;
        setDetail(d);
        setTicked((old) => (old.length ? old : d.versions.slice(0, 1).map((v) => v.id)));
      },
      (e) => setError(String(e)),
    );

  useEffect(() => {
    void loadFiles();
    const onHash = () => {
      const h = parseHash(location.hash);
      if (h.tab !== model.id) return;
      // The nav link has no file id: keep the selected file and put its id back in the URL.
      if (h.file) setFileId(h.file);
      else if (current.current) history.replaceState(null, "", `#/${model.id}/${current.current}`);
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, [model.base_url]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    audio.current?.pause();
    setDetail(undefined);
    setTicked([]);
    if (fileId) void loadDetail(fileId);
  }, [fileId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Full versions are fetched only when shown.
  useEffect(() => {
    if (!fileId) return;
    for (const id of ticked.filter((id) => !full[id]))
      get<Version>(`/v1beta/files/${fileId}/versions/${id}`).then((v) => setFull((f) => ({ ...f, [id]: v })), (e) => setError(String(e)));
  }, [ticked, fileId]); // eslint-disable-line react-hooks/exhaustive-deps

  const play = async (version: string, turn: number, start: number, end: number) => {
    const a = audio.current;
    if (!a || !fileId) return;
    if (playing?.version === version && playing.turn === turn) return a.pause();
    try {
      if (audioSrc.current?.file !== fileId || performance.now() - audioSrc.current.at > 600_000) {
        const d = await get<{ url: string }>(`/v1beta/files/${fileId}/audio`);
        a.src = d.url;
        audioSrc.current = { file: fileId, at: performance.now() };
      }
      stopAt.current = end;
      a.currentTime = start;
      setPlaying({ version, turn });
      await a.play();
    } catch (e) {
      setPlaying(undefined);
      setError(String(e));
    }
  };
  // timeupdate comes about every 250 ms in Chrome, so a frame loop stops the turn on time; timeupdate covers a hidden tab.
  const checkEnd = () => {
    const a = audio.current;
    if (a && !a.paused && a.currentTime >= stopAt.current) a.pause();
  };
  const watch = () => {
    checkEnd();
    if (audio.current && !audio.current.paused) requestAnimationFrame(watch);
  };

  const saveNames = async (version: string, names: Names) => {
    const res = await call(model, `/v1beta/files/${fileId}/versions/${version}/names`, { method: "PUT", headers: JSON_HDR, body: JSON.stringify(names) });
    if (!res.ok) return setError(`Names: ${await errorText(res)}`);
    const d: { names: Names } = await res.json();
    setFull((f) => (f[version] ? { ...f, [version]: { ...f[version], names: d.names } } : f));
  };

  const open = (id: string) => (location.hash = `#/${model.id}/${id}`);
  const tick = (id: string) => setTicked((old) => (old.includes(id) ? old.filter((x) => x !== id) : [...old, id].slice(-2)));

  const transcribe = async (id: string, signal: AbortSignal, timing: Timing) => {
    const body = { ...(lang ? { language_codes: [lang] } : {}), diarization: diarize, ...(label ? { label } : {}) };
    const path = `/v1beta/files/${id}/transcribe`;
    setCurl(curlFor(model, path, body));
    setBusy("Transcribing…");
    let res: Response;
    const sent = performance.now();
    try {
      res = await call(model, path, { method: "POST", headers: JSON_HDR, body: JSON.stringify(body), signal }, (n) => (setRetry(n), (timing.retries = n)));
    } catch (e) {
      // shortcut: the time includes 429 retries, so a network error late in a retry loop also reads as a timeout.
      if (!signal.aborted && gatewayTimedOut(undefined, performance.now() - sent)) throw new Error(TIMEOUT_MSG);
      throw e;
    }
    setRetry(undefined);
    timing.status = res.status;
    if (gatewayTimedOut(res.status, 0)) throw new Error(TIMEOUT_MSG);
    if (!res.ok) throw new Error(await errorText(res));
    const v: Version = await res.json();
    setFull((f) => ({ ...f, [v.id]: v }));
    if (current.current === id) setTicked([v.id]);
  };

  const run = async (work: (signal: AbortSignal, timing: Timing) => Promise<string | void>) => {
    abort.current?.abort();
    abort.current = new AbortController();
    const signal = abort.current.signal;
    setError(undefined);
    const t0 = performance.now();
    const timing: Timing = { retries: 0 };
    try {
      const id = await work(signal, timing);
      timing.totalMs = performance.now() - t0;
      void loadFiles();
      const target = id ?? current.current;
      if (target) void loadDetail(target);
    } catch (e) {
      if (!signal.aborted) setError(String(e));
    } finally {
      setT({ ...timing });
      setBusy("");
      setRetry(undefined);
    }
  };

  const upload = (file: File) =>
    run(async (signal, timing) => {
      setBusy("Uploading…");
      const start = performance.now();
      const mime = mimeOf(file);
      const up = await call(model, "/v1beta/uploads", { method: "POST", headers: JSON_HDR, body: JSON.stringify({ name: file.name, mime_type: mime, size_bytes: file.size }), signal });
      if (!up.ok) throw new Error(`Upload URL: ${await errorText(up)}`);
      const u = (await up.json()) as { id: string; upload_url: string; method: string; headers: Record<string, string> };
      // The signed URL needs no API key: plain fetch, not call().
      const put = await fetch(u.upload_url, { method: u.method, headers: u.headers, body: file, signal });
      if (!put.ok) throw new Error(`Upload: ${await errorText(put)}`);
      timing.firstMs = performance.now() - start;
      void loadFiles();
      open(u.id);
      await transcribe(u.id, signal, timing);
      return u.id;
    });

  const shown = ticked.map((id) => full[id]).filter(Boolean);
  return (
    <section className="panel stt">
      <div className="form">
        <label>
          Upload a file (up to 500 MB; it is kept, so you can transcribe it again later)
          <input type="file" accept="audio/*,.m4a,.webm" disabled={!!busy} onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
        </label>
        <div className="row">
          <b>Files</b>
          <button onClick={() => void (loadFiles(), fileId && loadDetail(fileId))}>Refresh</button>
        </div>
        <ul className="files">
          {files.length === 0 && <li className="muted">No files yet.</li>}
          {files.map((f) => (
            <li key={f.id}>
              <button className={`link${f.id === fileId ? " selected" : ""}`} onClick={() => open(f.id)}>
                {f.name}
              </button>{" "}
              <span className="muted">
                {f.versions} version{f.versions === 1 ? "" : "s"} · {(f.size_bytes / 1e6).toFixed(1)} MB · {when(f.created)}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div className="result">
        {detail ? (
          <>
            <b>
              File: {detail.file.name} <span className="muted">({(detail.file.size_bytes / 1e6).toFixed(1)} MB, {when(detail.file.created)})</span>
            </b>
            <div className="row">
              <label>
                Language
                <select value={lang} onChange={(e) => setLang(e.target.value)}>
                  <option value="">auto (detect)</option>
                  {LANGS.map((l) => (
                    <option key={l}>{l}</option>
                  ))}
                </select>
              </label>
              <label className="inline">
                <input type="checkbox" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} /> Speakers
              </label>
              <label>
                Label
                <input value={label} maxLength={200} placeholder="for example: after tuning" onChange={(e) => setLabel(e.target.value)} />
              </label>
            </div>
            <div className="row">
              <button className="primary" disabled={!!busy} onClick={() => void run((s, tm) => transcribe(detail.file.id, s, tm))}>
                Transcribe again
              </button>
              <button onClick={() => abort.current?.abort()}>Stop</button>
            </div>
            <table className="versions">
              <thead>
                <tr><th>Show</th><th>Time</th><th>Image</th><th>Lang</th><th>Spk</th><th>Label</th><th>Run</th></tr>
              </thead>
              <tbody>
                {detail.versions.map((v) => (
                  <tr key={v.id}>
                    <td><input type="checkbox" aria-label={`Show ${vtime(v.id)}`} checked={ticked.includes(v.id)} onChange={() => tick(v.id)} /></td>
                    <td>{vtime(v.id)}</td>
                    <td>{v.image_tag}</td>
                    <td>{v.settings.language_codes.join(",") || "auto"}</td>
                    <td>{v.speakers}</td>
                    <td>{v.label || "-"}</td>
                    <td>{v.run_seconds} s</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {detail.versions.length === 0 && <p className="muted">No versions yet. Press "Transcribe again".</p>}
          </>
        ) : (
          <p className="muted">{fileId ? "Loading the file…" : "Upload a file or pick one from the list."}</p>
        )}
        <Status error={error} retry={retry} />
        {busy && !retry && <p className="info">{busy}</p>}
        <div className={shown.length === 2 ? "compare" : ""}>
          {shown.map((v) => (
            <Transcript
              key={v.id}
              v={v}
              playing={playing?.version === v.id ? playing.turn : undefined}
              onPlay={(turn, start, end) => void play(v.id, turn, start, end)}
              onNames={(names) => saveNames(v.id, names)}
            />
          ))}
        </div>
        <audio ref={audio} hidden onPlaying={watch} onTimeUpdate={checkEnd} onPause={() => setPlaying(undefined)} onEnded={() => setPlaying(undefined)} onError={() => (setPlaying(undefined), audio.current?.src && setError("The audio cannot play in this browser."))} />
        <Timings t={t} firstLabel="Upload done" />
        <Curl text={curl} />
      </div>
    </section>
  );
}
