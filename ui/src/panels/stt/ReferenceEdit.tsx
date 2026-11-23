import { useRef } from "react";
import { COLORS, clock, groupTurns, nearestTurn, refSeconds, refSummary, speakerName, vtime, words, type Reference, type Version } from "./lib";

interface Props {
  text: string;
  language: string;
  saved?: Reference;
  version?: Version; // the working version (read only, left pane)
  onText: (t: string) => void;
  onLanguage: (l: string) => void;
  onSave: () => void;
  onDraft: () => void;
  onImport: (f: File) => void;
}

/** Start time of each editor line ("[00:00:01.0 - ...] Name: text"), or NaN for a line without a time. */
const lineStarts = (text: string) =>
  text.split("\n").map((l) => {
    const m = /^\s*\[\s*(\S+)\s+-/.exec(l);
    try {
      return m ? refSeconds(m[1]) : NaN;
    } catch {
      return NaN;
    }
  });

/** shortcut: the textarea wraps long lines, so a line's pixel offset is estimated from its length; good enough for
 * "close, not exact" (spec). Upgrade to a line-based editor if exact alignment is needed. */
function visualOffsets(ta: HTMLTextAreaElement, lines: string[]): { tops: number[]; lineHeight: number } {
  const st = getComputedStyle(ta);
  const lineHeight = parseFloat(st.lineHeight) || parseFloat(st.fontSize) * 1.4;
  const perLine = Math.max(10, Math.floor((ta.clientWidth - parseFloat(st.paddingLeft) - parseFloat(st.paddingRight)) / (parseFloat(st.fontSize) * 0.6)));
  const tops: number[] = [];
  let y = parseFloat(st.paddingTop);
  for (const l of lines) tops.push(y), (y += Math.max(1, Math.ceil(l.length / perLine)) * lineHeight);
  return { tops, lineHeight };
}

/** The Edit tab of the reference: the working version on the left (read only), the reference text on the right. */
export default function ReferenceEdit({ text, language, saved, version, onText, onLanguage, onSave, onDraft, onImport }: Props) {
  const left = useRef<HTMLDivElement>(null);
  const right = useRef<HTMLTextAreaElement>(null);
  const echo = useRef<"left" | "right" | null>(null); // the pane that the code scrolled: its scroll event is not a user scroll
  const sum = saved && refSummary(saved);
  const groups = version ? groupTurns(words(version)) : [];
  const speakers = [...new Set(groups.map((g) => g.speaker))];
  const starts = lineStarts(text);
  const timed = starts.some((s) => !Number.isNaN(s));

  const fromLeft = () => {
    if (echo.current === "left") return void (echo.current = null);
    const l = left.current, ta = right.current;
    if (!l || !ta || !timed) return;
    const row = [...l.querySelectorAll<HTMLElement>("[data-start]")].find((r) => r.offsetTop + r.offsetHeight > l.scrollTop);
    if (!row) return;
    const idx = starts.map((s, i) => [s, i]).filter(([s]) => !Number.isNaN(s));
    const k = nearestTurn(idx.map(([s]) => s), Number(row.dataset.start));
    const { tops } = visualOffsets(ta, text.split("\n"));
    echo.current = "right";
    ta.scrollTop = tops[idx[k][1]];
  };
  const fromRight = () => {
    if (echo.current === "right") return void (echo.current = null);
    const l = left.current, ta = right.current;
    if (!l || !ta || !timed || !groups.length) return;
    const { tops } = visualOffsets(ta, text.split("\n"));
    let i = tops.findIndex((t, j) => (tops[j + 1] ?? Infinity) > ta.scrollTop);
    while (i > 0 && Number.isNaN(starts[i])) i--;
    if (Number.isNaN(starts[i])) return;
    const k = nearestTurn(groups.map((g) => parseFloat(g.start)), starts[i]);
    const row = l.querySelectorAll<HTMLElement>("[data-start]")[k];
    if (!row) return;
    echo.current = "left";
    l.scrollTop = row.offsetTop - l.offsetTop;
  };

  return (
    <div className="stt-refedit">
      <div className="row stt-bar">
        {saved ? <span className="chip ok">✓ saved</span> : <span className="chip">not saved</span>}
        {sum && (
          <span className="muted">
            {sum.turns} turns · {sum.speakers.length} speakers · {sum.timed ? "times ✓" : "no times: no DER"}
          </span>
        )}
        <label>
          Language
          <input value={language} maxLength={20} placeholder="en" onChange={(e) => onLanguage(e.target.value)} />
        </label>
        <button onClick={onDraft} disabled={!version}>
          Draft from version
        </button>
        <label className="button">
          Import…
          <input type="file" aria-label="Import a reference" className="sr-only" accept=".txt,.json,text/plain,application/json" onChange={(e) => (e.target.files?.[0] && onImport(e.target.files[0]), (e.target.value = ""))} />
        </label>
        <button className="primary" disabled={!text.trim()} onClick={onSave}>
          Save
        </button>
      </div>
      <p className="muted">
        1 turn per line: <code>[00:00:00.0 - 00:00:04.9] Alice: Hello.</code> The times are optional (without them, no DER). JSON and Speechmatics JSON are also accepted.
      </p>
      <div className="stt-panes">
        <div className="stt-pane" ref={left} onScroll={fromLeft}>
          <div className="stt-pane-title">{version ? `Version ${vtime(version.id)} (read only)` : "Version"}</div>
          {!version && <p className="muted">Select a version to see it here.</p>}
          {groups.map((g, i) => (
            <p key={i} data-start={parseFloat(g.start)}>
              <span style={{ color: COLORS[speakers.indexOf(g.speaker) % COLORS.length], fontWeight: 600 }}>{speakerName(version?.names, g.speaker)}</span>{" "}
              <span className="muted">{clock(g.start)}</span> {g.text}
            </p>
          ))}
        </div>
        <textarea ref={right} aria-label="Reference" className="stt-pane" value={text} onScroll={fromRight} onChange={(e) => onText(e.target.value)} placeholder="Alice: Hello, this is the first speaker." />
      </div>
    </div>
  );
}
