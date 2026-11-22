import { useEffect, useRef, useState } from "react";
import { call, curlFor, errorText } from "../api";
import { Curl, Status, Timings, type Timing } from "../components";
import { parseHash, type ModelConfig } from "../config";

// STT-A with stored files and transcript history (spec: docs/specs/2026-11-21-stt-a-design.md).
// Every file goes through POST /v1beta/uploads (signed PUT). Each run of POST /v1beta/files/<id>/transcribe is saved
// as a version by the files service. 2 ticked versions show side by side.
// Evaluation: a reference (the correct transcript with speakers) per file. The files service scores each version against
// it (WER, cpWER, DER) and sums the scores per setup (GET /v1beta/scores).

export interface WordInfo {
  type: string;
  text: string;
  speaker?: string;
  start_offset: string;
  end_offset: string;
}
interface FileRow { id: string; name: string; mime_type: string; size_bytes: number; created: string; versions: number; latest: string | null; reference?: boolean }
export interface Setup { asr: string; aligner: string; diarization: string; image_tag: string }
interface Summary { id: string; created: string; label: string; image_tag: string; run_seconds: number; settings: { language_codes: string[]; diarization: boolean }; setup?: Setup | null; text_chars: number; speakers: number }
export interface RefTurn { speaker: string; text: string; start?: string | number; end?: string | number }
export interface Reference { language: string; turns: RefTurn[] }
interface Score { setup: string; wer: number; cpwer: number; der: { der: number; missed: number; false_alarm: number; confusion: number } | null; mapping: Record<string, string>; ref_speakers: number; hyp_speakers: number; speed: number | null }
interface SetupRow { setup: string; versions: number; files: number; wer: number | null; cpwer: number | null; der: number | null }
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

/** Seconds -> "00:01:02.5", the time format of a reference. */
export function refTime(sec: number): string {
  const t = Math.round(sec * 10) / 10;
  return `${String(Math.floor(t / 3600)).padStart(2, "0")}:${String(Math.floor(t / 60) % 60).padStart(2, "0")}:${(t % 60).toFixed(1).padStart(4, "0")}`;
}

/** Reference editor text -> PUT body. JSON as it is, or 1 turn per line: "[00:00:00.0 - 00:00:04.9] Alice: Hello" (times optional). */
export function parseReference(text: string, language: string): Reference {
  if (text.trim().startsWith("{")) return JSON.parse(text);
  const turns = text.split("\n").flatMap((line, i) => {
    if (!line.trim()) return [];
    const m = /^\s*(?:\[\s*(\S+)\s+-\s+(\S+)\s*\]\s*)?([^:]{1,40}):\s*(.*)$/.exec(line);
    if (!m) throw new Error(`Line ${i + 1}: write "Name: text" or "[00:00:00.0 - 00:00:04.9] Name: text"`);
    return [{ speaker: m[3].trim(), text: m[4].trim(), ...(m[1] ? { start: m[1], end: m[2] } : {}) }];
  });
  return { language, turns };
}

/** Reference -> editor text (the line form of parseReference). */
export const formatReference = (r: Reference) =>
  r.turns.map((t) => `${t.start !== undefined ? `[${t.start} - ${t.end}] ` : ""}${t.speaker}: ${t.text}`).join("\n");

/** A version as a reference draft: its turns with times and the given speaker names. The user corrects the text and the
 * speakers, then saves it as the reference. So a reviewed transcript becomes test data. */
export function draftFromVersion(annotations: WordInfo[], outputText: string, names: Names | undefined): string {
  if (!annotations.length) return outputText ? `Speaker: ${outputText.replace(/\s+/g, " ").trim()}` : "";
  return groupTurns(annotations)
    .map((g) => `[${refTime(parseFloat(g.start))} - ${refTime(parseFloat(g.end))}] ${g.speaker ? speakerName(names, g.speaker) : "Speaker"}: ${g.text}`)
    .join("\n");
}

const pct = (x: number | null | undefined) => (x == null ? "-" : `${(x * 100).toFixed(1)} %`);
const setupShort = (s: Setup | null | undefined) => (s ? `${s.asr} + ${s.diarization.split("/").pop()} @ ${s.image_tag}` : "unknown");
/** cpWER mapping -> names for PUT .../names (only spk_<n> labels). */
const mappingNames = (m: Record<string, string>): Names => Object.fromEntries(Object.entries(m).filter(([k]) => /^spk_\d{1,2}$/.test(k)));

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

function ScoreCells({ s, onNames }: { s?: Score; onNames: (n: Names) => void }) {
  if (!s) return <td colSpan={5} className="muted">…</td>;
  const map = Object.entries(s.mapping);
  const der = s.der && `missed ${pct(s.der.missed)}, false alarm ${pct(s.der.false_alarm)}, confusion ${pct(s.der.confusion)}`;
  return (
    <>
      <td><b>{pct(s.cpwer)}</b></td>
      <td>{pct(s.wer)}</td>
      <td title={der || "the reference has no times"}>{pct(s.der?.der)}</td>
      <td>{s.speed ? `${s.speed}x` : "-"}</td>
      <td>
        {map.map(([k, v]) => `${k || "no speaker"} → ${v}`).join(", ") || "-"}{" "}
        {Object.keys(mappingNames(s.mapping)).length > 0 && (
          <button className="link" title="Save the mapped reference names as the speaker names of this version" onClick={() => onNames(mappingNames(s.mapping))}>
            use as names
          </button>
        )}
      </td>
    </>
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
  const [refText, setRefText] = useState("");
  const [refLang, setRefLang] = useState("");
  const [hasRef, setHasRef] = useState(false);
  const [scores, setScores] = useState<Record<string, Score>>({});
  const [setups, setSetups] = useState<SetupRow[]>([]);
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
  const loadSetups = () => get<{ setups: SetupRow[] }>("/v1beta/scores").then((d) => setSetups(d.setups), (e) => setError(`Scores: ${e}`));
  const loadScores = (id: string, versions: Summary[]) =>
    Promise.all(versions.map((v) => get<Score>(`/v1beta/files/${id}/versions/${v.id}/score`).then((s) => [v.id, s] as const))).then(
      (list) => current.current === id && setScores(Object.fromEntries(list)),
      (e) => setError(`Scores: ${e}`),
    );
  const loadReference = async (id: string) => {
    const res = await call(model, `/v1beta/files/${id}/reference`, { method: "GET" });
    if (current.current !== id) return false;
    if (res.status === 404) return (setHasRef(false), setRefText(""), setRefLang(""), false);
    if (!res.ok) return (setError(`Reference: ${await errorText(res)}`), false);
    const r: Reference = await res.json();
    setHasRef(true);
    setRefText(formatReference(r));
    setRefLang(r.language);
    return true;
  };
  const loadDetail = (id: string) =>
    get<{ file: FileRow; versions: Summary[] }>(`/v1beta/files/${id}`).then(
      (d) => {
        if (current.current !== id) return;
        setDetail(d);
        setTicked((old) => (old.length ? old : d.versions.slice(0, 1).map((v) => v.id)));
        void loadReference(id).then((has) => has && loadScores(id, d.versions));
      },
      (e) => setError(String(e)),
    );

  useEffect(() => {
    void loadFiles();
    void loadSetups();
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
    setScores({});
    setHasRef(false);
    setRefText("");
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

  const saveReference = async () => {
    if (!fileId) return;
    let body: Reference;
    try {
      body = parseReference(refText, refLang);
    } catch (e) {
      return setError(`Reference: ${e instanceof Error ? e.message : e}`);
    }
    const res = await call(model, `/v1beta/files/${fileId}/reference`, { method: "PUT", headers: JSON_HDR, body: JSON.stringify(body) });
    if (!res.ok) return setError(`Reference: ${await errorText(res)}`);
    setError(undefined);
    void loadFiles();
    void loadDetail(fileId);
    void loadSetups();
  };
  const draftReference = () => {
    const v = ticked.map((id) => full[id]).find(Boolean);
    if (!v) return setError("Tick a version first: its turns become the draft.");
    if (refText.trim() && !confirm("Replace the text in the editor with the ticked version?")) return;
    setRefText(draftFromVersion(words(v), v.response.output_text ?? "", v.names));
    setRefLang(v.settings.language_codes[0] ?? refLang);
  };
  const readRefFile = (f: File) => void f.text().then(setRefText);

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
      void loadSetups();
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
          <button onClick={() => void (setError(undefined), loadFiles(), loadSetups(), fileId && loadDetail(fileId))}>Refresh</button>
        </div>
        {setups.length > 0 && (
          <>
            <b>Accuracy per setup</b>
            <p className="muted">Mean over the versions of files with a reference. Lower is better.</p>
            <table className="versions setups">
              <thead>
                <tr><th>Setup</th><th>Files</th><th>Versions</th><th title="text and speakers">cpWER</th><th title="text only">WER</th><th title="speaker time, 0.25 s collar">DER</th></tr>
              </thead>
              <tbody>
                {setups.map((r) => (
                  <tr key={r.setup}>
                    <td>{r.setup}</td><td>{r.files}</td><td>{r.versions}</td><td><b>{pct(r.cpwer)}</b></td><td>{pct(r.wer)}</td><td>{pct(r.der)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <ul className="files">
          {files.length === 0 && <li className="muted">No files yet.</li>}
          {files.map((f) => (
            <li key={f.id}>
              <button className={`link${f.id === fileId ? " selected" : ""}`} onClick={() => open(f.id)}>
                {f.name}
              </button>{" "}
              <span className="muted">
                {f.versions} version{f.versions === 1 ? "" : "s"}{f.reference ? " · reference" : ""} · {(f.size_bytes / 1e6).toFixed(1)} MB · {when(f.created)}
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
                <tr>
                  <th>Show</th><th>Time</th><th>Setup</th><th>Lang</th><th>Spk</th><th>Label</th><th>Run</th>
                  {hasRef && (<><th title="text and speakers">cpWER</th><th title="text only">WER</th><th title="speaker time, 0.25 s collar">DER</th><th title="audio seconds per run second">Speed</th><th>Mapping</th></>)}
                </tr>
              </thead>
              <tbody>
                {detail.versions.map((v) => (
                  <tr key={v.id}>
                    <td><input type="checkbox" aria-label={`Show ${vtime(v.id)}`} checked={ticked.includes(v.id)} onChange={() => tick(v.id)} /></td>
                    <td>{vtime(v.id)}</td>
                    <td title={v.setup ? JSON.stringify(v.setup) : "a version made before the setup record"}>{setupShort(v.setup)}</td>
                    <td>{v.settings.language_codes.join(",") || "auto"}</td>
                    <td>{scores[v.id] ? `${v.speakers} of ${scores[v.id].ref_speakers}` : v.speakers}</td>
                    <td>{v.label || "-"}</td>
                    <td>{v.run_seconds} s</td>
                    {hasRef && <ScoreCells s={scores[v.id]} onNames={(n) => void saveNames(v.id, n)} />}
                  </tr>
                ))}
              </tbody>
            </table>
            {detail.versions.length === 0 && <p className="muted">No versions yet. Press "Transcribe again".</p>}
            <details className="reference">
              <summary>
                <b>Reference</b> <span className="muted">{hasRef ? "(saved: the versions get scores)" : "(none: add the correct transcript to score the versions)"}</span>
              </summary>
              <p className="muted">
                1 turn per line: <code>[00:00:00.0 - 00:00:04.9] Alice: Hello.</code> The times are optional (without them, no DER). JSON is also accepted. Or tick a version, press "Draft from version",
                then correct the text and the speakers.
              </p>
              <textarea aria-label="Reference" rows={8} value={refText} onChange={(e) => setRefText(e.target.value)} placeholder="Alice: Hello, this is the first speaker." />
              <div className="row">
                <label>
                  Language
                  <input value={refLang} maxLength={20} placeholder="en" onChange={(e) => setRefLang(e.target.value)} />
                </label>
                <button onClick={draftReference}>Draft from version</button>
                <label>
                  Load a file
                  <input type="file" accept=".json,.txt,text/plain,application/json" onChange={(e) => e.target.files?.[0] && readRefFile(e.target.files[0])} />
                </label>
                <button className="primary" disabled={!refText.trim()} onClick={() => void saveReference()}>
                  Save reference
                </button>
              </div>
            </details>
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
