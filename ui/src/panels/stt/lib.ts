// Types and pure functions of the STT panel (no React). Tested in ui/src/lib.test.ts.
export interface WordInfo {
  type: string;
  text: string;
  speaker?: string;
  start_offset: string;
  end_offset: string;
}
export interface FileRow { id: string; name: string; mime_type: string; size_bytes: number; created: string; versions: number; latest: string | null; reference?: boolean }
export interface Setup { asr: string; aligner: string; diarization: string; image_tag: string }
export interface Summary { id: string; created: string; label: string; image_tag: string; run_seconds: number; settings: { language_codes: string[]; diarization: boolean }; setup?: Setup | null; text_chars: number; speakers: number }
export interface RefTurn { speaker: string; text: string; start?: string | number; end?: string | number }
export interface Reference { language: string; turns: RefTurn[] }
export interface Score { setup: string; wer: number; cpwer: number; der: { der: number; missed: number; false_alarm: number; confusion: number } | null; mapping: Record<string, string>; ref_speakers: number; hyp_speakers: number; speed: number | null }
export interface SetupRow { setup: string; versions: number; files: number; wer: number | null; cpwer: number | null; der: number | null }
export type Names = Record<string, string>; // per version: {"spk_1": "Alice"} (PUT .../versions/<id>/names)
export interface Version extends Omit<Summary, "text_chars" | "speakers"> { names?: Names; response: { output_text?: string; steps?: { content?: { annotations?: WordInfo[] }[] }[] } }

export const LANGS = ["zh", "en", "yue", "ar", "de", "fr", "es", "pt", "id", "it", "ko", "ru", "th", "vi", "ja", "tr", "hi", "ms", "nl", "sv", "da", "fi", "pl", "cs", "fil", "fa", "el", "hu", "mk", "ro"];
// The files service accepts only these types. Browsers give other names (audio/x-m4a) or none.
export const MIME: Record<string, string> = { mp3: "audio/mpeg", wav: "audio/wav", m4a: "audio/m4a", ogg: "audio/ogg", flac: "audio/flac", webm: "audio/webm", aac: "audio/aac", opus: "audio/opus", aiff: "audio/aiff", aif: "audio/aiff" };
export const COLORS = ["#2563eb", "#d97706", "#059669", "#dc2626", "#7c3aed", "#db2777", "#0891b2", "#65a30d"];
export const JSON_HDR = { "Content-Type": "application/json" };

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
export const TIMEOUT_MSG = "The gateway stopped waiting after 300 s. The run can still finish. Press Refresh in a few minutes.";

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

export const pct = (x: number | null | undefined) => (x == null ? "-" : `${(x * 100).toFixed(1)} %`);
export const setupShort = (s: Setup | null | undefined) => (s ? `${s.asr} + ${s.diarization.split("/").pop()} @ ${s.image_tag}` : "unknown");
/** cpWER mapping -> names for PUT .../names (only spk_<n> labels). */
export const mappingNames = (m: Record<string, string>): Names => Object.fromEntries(Object.entries(m).filter(([k]) => /^spk_\d{1,2}$/.test(k)));

export const speakerCount = (annotations: WordInfo[]) => new Set(annotations.map((w) => w.speaker).filter(Boolean)).size;

export const mimeOf = (f: File) => MIME[f.name.split(".").pop()?.toLowerCase() ?? ""] ?? (f.type || "audio/wav");
export const words = (v: Version) => v.response.steps?.[0]?.content?.[0]?.annotations ?? [];
export const when = (iso: string) => iso.replace("T", " ").replace(/:\d\dZ$/, "");
export const vtime = (id: string) => `${id.slice(0, 4)}-${id.slice(4, 6)}-${id.slice(6, 8)} ${id.slice(9, 11)}:${id.slice(11, 13)}`;

/** A reference time -> seconds. The twin of seconds() in stt_api/evaluation/reference.py: 12.5, "12.5", "12.5s",
 * "01:02.5" or "00:01:02.5". */
export function refSeconds(value: string | number): number {
  if (typeof value === "number") return value;
  const parts = value.trim().replace(/s$/, "").split(":");
  if (parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) throw new Error(`bad time ${JSON.stringify(value)}`);
  return parts.reduce((t, p) => t * 60 + parseFloat(p), 0);
}

interface SmItem { type?: string; start_time?: number; end_time?: number; attaches_to?: string; alternatives?: { content?: string; speaker?: string }[] }

/** A Speechmatics JSON transcript -> a reference: consecutive items of 1 speaker make 1 turn, punctuation joins the
 * word before it, an entity keeps its written form (content). */
export function speechmaticsToReference(doc: unknown): Reference {
  const d = doc as { results?: unknown; metadata?: { transcription_config?: { language?: string } } };
  if (!d || !Array.isArray(d.results)) throw new Error("not a Speechmatics transcript");
  const turns: { speaker: string; text: string; start: number; end: number }[] = [];
  for (const x of d.results as SmItem[]) {
    const a = x.alternatives?.[0] ?? {};
    const speaker = a.speaker || "unknown";
    const text = a.content ?? "";
    const [start, end] = [x.start_time ?? 0, x.end_time ?? 0];
    const last = turns.at(-1);
    if (last && last.speaker === speaker) {
      last.text += x.attaches_to === "previous" ? text : ` ${text}`;
      last.end = Math.max(last.end, end);
    } else turns.push({ speaker, start, end, text });
  }
  return { language: d.metadata?.transcription_config?.language ?? "", turns };
}

/** Text of an imported file -> a reference: Speechmatics JSON, else the editor formats (parseReference). */
export function importReference(text: string, language: string): Reference {
  let doc: unknown;
  try {
    doc = JSON.parse(text);
  } catch {
    return parseReference(text, language);
  }
  if (doc && typeof doc === "object" && "results" in doc) {
    const r = speechmaticsToReference(doc);
    return { ...r, language: r.language || language };
  }
  return parseReference(text, language);
}

export const renameRefSpeaker = (r: Reference, from: string, to: string): Reference => ({ ...r, turns: r.turns.map((t) => (t.speaker === from ? { ...t, speaker: to } : t)) });

export function refSummary(r: Reference): { turns: number; speakers: string[]; timed: boolean } {
  return { turns: r.turns.length, speakers: [...new Set(r.turns.map((t) => t.speaker))], timed: r.turns.length > 0 && r.turns.every((t) => t.start !== undefined && t.end !== undefined) };
}

/** Seconds of speech per reference speaker; null for each speaker when the reference has no times. */
export function speechTime(r: Reference): Record<string, number | null> {
  const timed = refSummary(r).timed;
  const out: Record<string, number | null> = {};
  for (const t of r.turns) out[t.speaker] = timed ? (out[t.speaker] ?? 0)! + refSeconds(t.end!) - refSeconds(t.start!) : null;
  return out;
}

export const scoreTone = (cpwer: number): "ok" | "warn" | "bad" => (cpwer < 0.2 ? "ok" : cpwer <= 0.4 ? "warn" : "bad");

export function bestCpwer(rows: { file_id: string; cpwer: number }[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of rows) if (!(r.file_id in out) || r.cpwer < out[r.file_id]) out[r.file_id] = r.cpwer;
  return out;
}

/** The score of the next older version that has one (versions are newest first). */
export function previousScore(versions: Summary[], scores: Record<string, Score>, id: string): Score | undefined {
  const i = versions.findIndex((v) => v.id === id);
  return i < 0 ? undefined : versions.slice(i + 1).map((v) => scores[v.id]).find(Boolean);
}

/** "Apply to all versions": the names of target after a fill from source, through the reference speaker that both
 * map to. A saved name is never overwritten. null when nothing changes. */
export function applyNames(source: { names: Names; mapping: Record<string, string> }, target: { names: Names; mapping: Record<string, string> }): Names | null {
  const refName: Record<string, string> = {};
  for (const [label, ref] of Object.entries(source.mapping)) if (source.names[label]?.trim()) refName[ref] = source.names[label].trim();
  const out = { ...target.names };
  let changed = false;
  for (const [label, ref] of Object.entries(target.mapping))
    if (/^spk_\d{1,2}$/.test(label) && !out[label]?.trim() && refName[ref]) (out[label] = refName[ref]), (changed = true);
  return changed ? out : null;
}

/** Index of the last start at or before t (0 when t is before the first start, -1 for no starts). */
export function nearestTurn(starts: number[], t: number): number {
  if (!starts.length) return -1;
  let i = 0;
  while (i + 1 < starts.length && starts[i + 1] <= t) i++;
  return i;
}

export type View = "transcript" | "edit" | "evaluation" | "speakers";
const REF_VIEWS_ALL: View[] = ["edit", "evaluation", "speakers"];

/** URL parts -> the selected row, the working version and the view, with the fallbacks of the spec ("URL"). */
export function resolveView(versions: { id: string }[], h: { row?: string; view?: string; v?: string }, hasRef: boolean): { row: string; working?: string; view: View; noVersions: boolean } {
  const has = (id?: string) => !!id && versions.some((v) => v.id === id);
  const row = h.row === "ref" || has(h.row) ? h.row! : (versions[0]?.id ?? "ref");
  const working = row !== "ref" ? row : has(h.v) ? h.v : versions[0]?.id;
  const view: View = row !== "ref" ? "transcript" : hasRef && REF_VIEWS_ALL.includes(h.view as View) ? (h.view as View) : "edit";
  return { row, working, view, noVersions: versions.length === 0 };
}

/** The editor text is not the saved reference (typed or imported): a reload must not replace it. */
export const hasUnsavedEdits = (text: string, saved?: Reference) => text.trim() !== (saved ? formatReference(saved) : "").trim();
