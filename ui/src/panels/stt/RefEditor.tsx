import { useEffect, useRef, useState } from "react";
import { COLORS, formatReference, insertTurn, mergeTurns, parseReference, refSeconds, refSummary, vtime, type RefTurn, type Reference, type Version } from "./lib";

interface Props {
  fileName: string;
  text: string; // the editor draft in the line format; the parent keeps it (unsaved edits survive a reload)
  language: string;
  saved?: Reference;
  version?: Version; // the working version: the source of "Draft from version"
  playing?: string;
  onText: (t: string) => void;
  onLanguage: (l: string) => void;
  onSave: () => void;
  onDraft: () => void;
  onImport: (f: File) => void;
  onBack: () => void;
  onPlay: (key: string, start: number, end: number) => void;
}

const secs = (v?: string | number) => {
  if (v === undefined || v === "") return undefined;
  try {
    return refSeconds(v);
  } catch {
    return NaN;
  }
};
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const parse = (text: string, language: string): RefTurn[] => (text.trim() ? parseReference(text, language).turns : []);

/** The reference editor page: 1 card per turn (speaker, times, ▶, text), a speaker bar, and a raw text mode. */
export default function RefEditor({ fileName, text, language, saved, version, playing, onText, onLanguage, onSave, onDraft, onImport, onBack, onPlay }: Props) {
  const [raw, setRaw] = useState(false);
  const [parseError, setParseError] = useState<string>();
  const [turns, setTurns] = useState<RefTurn[]>([]);
  const [rename, setRename] = useState<{ from: string; to: string }>();
  const emitted = useRef<string | null>(null); // the text this page wrote last: a different text came from outside

  useEffect(() => {
    if (text === emitted.current) return;
    try {
      setTurns(parse(text, language));
      setParseError(undefined);
    } catch (e) {
      setRaw(true); // the text is not in the line format: keep it as text, show why
      setParseError(e instanceof Error ? e.message : String(e));
    }
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => (e.metaKey || e.ctrlKey) && e.key === "s" && (e.preventDefault(), onSave());
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [onSave]);

  const update = (next: RefTurn[]) => {
    setTurns(next);
    const t = formatReference({ language, turns: next });
    emitted.current = t;
    onText(t);
  };
  const edit = (i: number, patch: Partial<RefTurn>) => update(turns.map((t, k) => (k === i ? { ...t, ...patch } : t)));
  const setTime = (i: number, key: "start" | "end", v: string) => {
    const t = { ...turns[i], [key]: v };
    if (!t.start && !t.end) (delete t.start, delete t.end); // both empty: a turn without times
    update(turns.map((x, k) => (k === i ? t : x)));
  };
  const toRaw = () => setRaw(true);
  const toTurns = () => {
    try {
      setTurns(parse(text, language));
      setParseError(undefined);
      setRaw(false);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : String(e));
    }
  };

  const speakers = [...new Set(turns.map((t) => t.speaker))];
  const color = (s: string) => COLORS[speakers.indexOf(s) % COLORS.length];
  const stats = Object.fromEntries(
    speakers.map((s) => {
      const own = turns.filter((t) => t.speaker === s);
      const time = own.reduce((n, t) => n + Math.max(0, (secs(t.end) ?? 0) - (secs(t.start) ?? 0) || 0), 0);
      return [s, { turns: own.length, time }];
    }),
  );
  const unsaved = !saved || text.trim() !== formatReference(saved).trim();
  const sum = refSummary({ language, turns });
  const pickSpeaker = (i: number, v: string) => {
    if (v !== "\u0000new") return edit(i, { speaker: v });
    const name = prompt("Name of the new speaker")?.replace(/:/g, "").trim();
    if (name) edit(i, { speaker: name.slice(0, 40) });
  };
  const applyRename = () => {
    const to = rename?.to.replace(/:/g, "").trim();
    if (rename && to && to !== rename.from) update(turns.map((t) => (t.speaker === rename.from ? { ...t, speaker: to.slice(0, 40) } : t)));
    setRename(undefined);
  };

  return (
    <div className="refed">
      <div className="row refed-head">
        <button onClick={onBack}>← Back</button>
        <b>Reference of {fileName}</b>
        {unsaved ? <span className="chip warn">unsaved changes</span> : <span className="chip ok">✓ saved</span>}
        <span className="muted">
          {sum.turns} turns · {sum.speakers.length} speakers · {sum.timed ? "times ✓" : "some turns have no times: no DER"}
        </span>
        <span style={{ flex: 1 }} />
        <label className="inline">
          Language <input className="refed-lang" value={language} maxLength={20} placeholder="en" onChange={(e) => onLanguage(e.target.value)} />
        </label>
        <button onClick={onDraft} disabled={!version} title="Replace the text with the turns of the working version">
          Draft from {version ? `version ${vtime(version.id)}` : "a version"}
        </button>
        <label className="button">
          Import…
          <input type="file" aria-label="Import a reference" className="sr-only" accept=".txt,.json,text/plain,application/json" onChange={(e) => (e.target.files?.[0] && onImport(e.target.files[0]), (e.target.value = ""))} />
        </label>
        <button aria-pressed={raw} onClick={raw ? toTurns : toRaw}>
          {raw ? "Turn view" : "Raw text"}
        </button>
        <button className="primary" disabled={!text.trim() || !unsaved} onClick={onSave} title="Save (Cmd+S / Ctrl+S)">
          Save
        </button>
      </div>
      {parseError && <p className="error">{parseError}</p>}

      {raw ? (
        <>
          <p className="muted">
            1 turn per line: <code>[00:00:00.0 - 00:00:04.9] Alice: Hello.</code> The times are optional (without them, no DER). JSON and Speechmatics JSON are also accepted
            by Import.
          </p>
          <textarea aria-label="Reference" className="refed-raw" value={text} spellCheck onChange={(e) => (onText(e.target.value), setParseError(undefined))} />
        </>
      ) : (
        <>
          <div className="refed-speakers">
            <span className="muted">Speakers:</span>
            {speakers.map((s) =>
              rename?.from === s ? (
                <span key={s} className="refed-rename">
                  <input autoFocus aria-label={`New name of ${s}`} value={rename.to} maxLength={40} onChange={(e) => setRename({ from: s, to: e.target.value })} onKeyDown={(e) => (e.key === "Enter" ? applyRename() : e.key === "Escape" && setRename(undefined))} />
                  <button onClick={applyRename}>Rename</button>
                </span>
              ) : (
                <button key={s} className="chip refed-spk" style={{ borderColor: color(s), color: color(s) }} title="Rename this speaker in every turn" onClick={() => setRename({ from: s, to: s })}>
                  {s} <span className="muted">· {stats[s].turns} turn{stats[s].turns === 1 ? "" : "s"}{stats[s].time ? ` · ${mmss(stats[s].time)}` : ""}</span> ✎
                </button>
              ),
            )}
            <span className="muted">Click a speaker to rename it in every turn. The change is saved with Save.</span>
          </div>
          {turns.length === 0 && (
            <div className="refed-empty">
              <p>No turns yet. Start from a model version, import a file, or add the first turn.</p>
              <button onClick={() => update(insertTurn(turns, -1))}>＋ Add the first turn</button>
            </div>
          )}
          <ol className="refed-turns">
            {turns.map((t, i) => {
              const [s, e] = [secs(t.start), secs(t.end)];
              const timesOk = s !== undefined && e !== undefined && !Number.isNaN(s) && !Number.isNaN(e) && e >= s;
              const key = `ref:${i}`;
              return (
                <li key={i} className="refed-turn" style={{ borderLeftColor: color(t.speaker) }}>
                  <div className="refed-meta">
                    <select aria-label={`Speaker of turn ${i + 1}`} value={t.speaker} style={{ color: color(t.speaker) }} onChange={(ev) => pickSpeaker(i, ev.target.value)}>
                      {speakers.map((x) => (
                        <option key={x} value={x}>
                          {x}
                        </option>
                      ))}
                      <option value={"\u0000new"}>＋ New speaker…</option>
                    </select>
                    <span className="refed-times">
                      <input aria-label={`Start of turn ${i + 1}`} className={Number.isNaN(s) ? "bad" : ""} value={t.start ?? ""} placeholder="00:00:00.0" onChange={(ev) => setTime(i, "start", ev.target.value)} />
                      –
                      <input aria-label={`End of turn ${i + 1}`} className={Number.isNaN(e) || (timesOk === false && s !== undefined && e !== undefined && e < s) ? "bad" : ""} value={t.end ?? ""} placeholder="00:00:00.0" onChange={(ev) => setTime(i, "end", ev.target.value)} />
                    </span>
                    <button className="play" disabled={!timesOk} aria-label={`${playing === key ? "Stop" : "Play"} turn ${i + 1}`} title={timesOk ? "Play this turn" : "Add valid times to play"} onClick={() => timesOk && onPlay(key, s!, e!)}>
                      {playing === key ? "■" : "▶"}
                    </button>
                    <span style={{ flex: 1 }} />
                    <span className="refed-actions">
                      <button title="Add an empty turn below" onClick={() => update(insertTurn(turns, i))}>＋</button>
                      <button title="Merge with the next turn" disabled={i === turns.length - 1} onClick={() => update(mergeTurns(turns, i))}>⤓ merge</button>
                      <button title="Delete this turn" onClick={() => update(turns.filter((_, k) => k !== i))}>✕</button>
                    </span>
                  </div>
                  <textarea aria-label={`Text of turn ${i + 1}`} className="refed-text" rows={1} value={t.text} spellCheck placeholder="What this speaker says" onChange={(ev) => edit(i, { text: ev.target.value.replace(/\s*\n\s*/g, " ") })} />
                </li>
              );
            })}
          </ol>
        </>
      )}
    </div>
  );
}
