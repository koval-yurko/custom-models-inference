import { useMemo, useRef, useState } from "react";
import { compare, refSide, samples, versionSide, type Cell, type Row, type Seg } from "./align";
import { COLORS, clock, speakerName, vtime, words, type Names, type Reference, type Summary, type Version } from "./lib";

interface Props {
  reference?: Reference;
  versions: Summary[];
  a: string; // "ref" or a version id (left side)
  b: string; // a version id (right side)
  va?: Version; // the full left version (when a is a version)
  vb?: Version;
  playing?: string; // the key of the part that plays now
  onAB: (a: string, b: string) => void;
  onBack: () => void;
  onPlay: (key: string, start: number, end: number) => void;
  onRenameRef: (renames: [string, string][]) => Promise<void>;
  onSaveNames: (version: string, names: Names) => Promise<void>;
}

type Side = "a" | "b";
const WORD_CLASS: Record<Cell["op"], string> = { ok: "", sub: "w-sub", del: "w-del", ins: "w-ins" };
const PROBLEM_TEXT = { merged: "Merged: 2 or more speakers of the left side are 1 speaker here", split: "Split: mostly 1 left speaker, who already has another label", "no match": "No match on the left side" };
const pct = (x: number) => `${Math.round(x * 100)} %`;
const dur = (s: { start?: number; end?: number }) => (s.start !== undefined && s.end !== undefined ? s.end - s.start : 0);
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

/** The compare page: 2 transcripts of 1 file as aligned rows, with word and speaker marks (spec: docs/specs/2026-11-24-stt-compare-design.md). */
export default function Compare({ reference, versions, a, b, va, vb, playing, onAB, onBack, onPlay, onRenameRef, onSaveNames }: Props) {
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [filter, setFilter] = useState<string>(); // "rightSpeaker|leftSpeaker"
  const [cursor, setCursor] = useState(-1);
  const [box, setBox] = useState<{ side: Side; speaker: string; x: number; y: number }>();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [boxError, setBoxError] = useState<string>();
  const rowEls = useRef<(HTMLDivElement | null)[]>([]);

  const result = useMemo(() => {
    if (a === "ref" ? !reference : !va) return undefined;
    if (!vb) return undefined;
    try {
      const A = a === "ref" ? refSide(reference!) : versionSide(words(va!));
      return compare(A, versionSide(words(vb)));
    } catch (e) {
      return { error: e instanceof Error ? e.message : String(e) };
    }
  }, [a, reference, va, vb]);

  const label = (id: string) => (id === "ref" ? "Reference" : `Version ${vtime(id)}${versions.find((v) => v.id === id)?.label ? ` · ${versions.find((v) => v.id === id)!.label}` : ""}`);
  const picker = (value: string, withRef: boolean, onChange: (x: string) => void, aria: string) => (
    <select aria-label={aria} value={value} onChange={(e) => onChange(e.target.value)}>
      {withRef && reference && <option value="ref">Reference</option>}
      {versions.map((v) => (
        <option key={v.id} value={v.id}>
          {label(v.id)}
        </option>
      ))}
    </select>
  );
  const head = (
    <div className="row cmp-head">
      <button onClick={onBack}>← Back</button>
      <b>Compare</b>
      {picker(a, true, (x) => (setBox(undefined), onAB(x, b)), "Left side")}
      <span>↔</span>
      {picker(b, false, (x) => (setBox(undefined), onAB(a, x)), "Right side")}
    </div>
  );
  if (!a || !b) return (<div className="cmp">{head}<p className="info">Compare needs a reference and 1 version, or 2 versions.</p></div>);
  if (!result) return (<div className="cmp">{head}<p className="muted">Loading the 2 transcripts…</p></div>);
  if ("error" in result) return (<div className="cmp">{head}<p className="error">{result.error}</p></div>);

  const { rows, map } = result;
  const leftSpeakers = [...new Set(rows.flatMap((r) => (r.left ? [r.left.speaker] : [])))];
  const leftName = (s: string) => (a === "ref" ? s : speakerName(va?.names, s));
  const rightName = (s: string) => speakerName(vb?.names, s);
  const color = (leftSpk?: string) => (leftSpk && leftSpeakers.includes(leftSpk) ? COLORS[leftSpeakers.indexOf(leftSpk) % COLORS.length] : "#777");
  /** "spk_2 → Bob", or only "Bob" when the right name is already the matched left name. */
  const rightLabel = (s: string) => {
    if (!s) return "no speaker";
    const m = map.match[s] ? leftName(map.match[s]) : "?";
    return rightName(s) === m ? m : `${rightName(s)} → ${m}`;
  };
  const chipStyle = (c: string) => ({ background: `color-mix(in srgb, ${c} 16%, transparent)`, color: c });
  const errRows = rows.map((r, i) => (r.words + r.speakers ? i : -1)).filter((i) => i >= 0);
  const shown = rows.map((r, i) => [r, i] as const).filter(([r]) => (!onlyErrors || r.words + r.speakers) && (!filter || r.pairs.includes(filter)));
  const totalWords = rows.reduce((s, r) => s + r.words, 0), totalSpk = rows.reduce((s, r) => s + r.speakers, 0);

  const jump = (i: number) => (setCursor(i), requestAnimationFrame(() => rowEls.current[i]?.scrollIntoView({ block: "center", behavior: "smooth" })));
  const step = (dir: 1 | -1) => {
    const next = dir > 0 ? errRows.find((i) => i > cursor) : [...errRows].reverse().find((i) => i < cursor);
    if (next !== undefined) (setOnlyErrors(false), setFilter(undefined), jump(next));
  };
  const BINS = Math.min(rows.length, 120);
  const bins = Array.from({ length: BINS }, (_, k) => {
    const part = rows.slice(Math.floor((k * rows.length) / BINS), Math.floor(((k + 1) * rows.length) / BINS));
    return { first: Math.floor((k * rows.length) / BINS), tone: part.some((r) => r.speakers) ? "spk" : part.some((r) => r.words) ? "word" : "ok" };
  });

  const openBox = (side: Side, speaker: string, el: HTMLElement) => {
    if (!speaker) return;
    const r = el.getBoundingClientRect();
    setName(side === "a" ? (a === "ref" ? speaker : (va?.names?.[speaker] ?? "")) : (vb?.names?.[speaker] ?? ""));
    setBoxError(undefined);
    setBox({ side, speaker, x: Math.min(r.left, innerWidth - 330), y: r.bottom + 4 });
  };
  const saveBox = async () => {
    if (!box || !name.trim() || saving) return;
    setSaving(true);
    try {
      if (box.side === "a" && a === "ref") await onRenameRef([[box.speaker, name.trim()]]);
      else {
        const v = box.side === "a" ? va : vb;
        if (v) await onSaveNames(v.id, { ...(v.names ?? {}), [box.speaker]: name.trim() });
      }
      setBox(undefined);
    } catch (e) {
      setBoxError(e instanceof Error ? e.message : String(e)); // the box stays open with the error: nothing was saved
    } finally {
      setSaving(false);
    }
  };

  const playBtn = (key: string, s: { start?: number; end?: number }, what: string) =>
    s.start !== undefined && s.end !== undefined ? (
      <button className="play" aria-label={`${playing === key ? "Stop" : "Play"} ${what}`} onClick={() => onPlay(key, s.start!, s.end!)}>
        {playing === key ? "■" : "▶"}
      </button>
    ) : null;
  const leftChip = (s: Seg) => (
    <button className="chip" style={chipStyle(color(s.speaker))} onClick={(e) => openBox("a", s.speaker, e.currentTarget)}>
      {leftName(s.speaker) || "no speaker"}
    </button>
  );
  const rightChip = (s: Seg) => {
    const m = map.match[s.speaker];
    const bad = map.hasSpeakers && s.cells.some((c) => c.wrongSpk);
    return (
      <button className={`chip${bad ? " bad" : ""}`} style={chipStyle(color(m))} onClick={(e) => openBox("b", s.speaker, e.currentTarget)}>
        {rightLabel(s.speaker)}
      </button>
    );
  };
  const cells = (cs: Cell[]) =>
    cs.map((c, k) => (
      <span key={k}>
        {k > 0 && " "}
        <span className={`${WORD_CLASS[c.op]}${c.wrongSpk ? " w-spk" : ""}`} title={c.wrongSpk ? "right word, wrong speaker" : c.op === "sub" ? "wrong word" : c.op === "del" ? "missed word" : c.op === "ins" ? "extra word" : undefined}>
          {c.text}
        </span>
      </span>
    ));
  const rightSide = (r: Row, i: number) =>
    r.right.length === 0 ? <span className="muted">not in the right side</span> : r.right.map((s, k) => (
      <span key={k} className="cmp-seg">
        {playBtn(`b:${i}:${k}`, s, `right part ${i + 1}.${k + 1}`)}
        {rightChip(s)}
        {cells(s.cells)}
      </span>
    ));

  // speaker box data
  const boxSegs = box ? (box.side === "a" ? rows.flatMap((r) => (r.left ? [r.left] : [])) : rows.flatMap((r) => r.right)) : [];
  const boxSamples = box ? samples(boxSegs, box.speaker) : [];
  const shares = !box ? [] : box.side === "b"
    ? Object.entries(map.counts[box.speaker] ?? {}).map(([s, c]) => [leftName(s), c] as const)
    : Object.entries(map.counts).flatMap(([rs, row]) => (row[box.speaker] ? [[rs ? rightName(rs) : "no speaker", row[box.speaker]] as const] : []));
  const sharesTotal = shares.reduce((s, [, c]) => s + c, 0);

  return (
    <div className="cmp">
      {head}
      <div className="row cmp-summary">
        <span className="chip w-sub">{totalWords} word error{totalWords === 1 ? "" : "s"}</span>
        {map.hasSpeakers && <span className="chip w-spk">{totalSpk} word{totalSpk === 1 ? "" : "s"} with the wrong speaker</span>}
        <span className="muted">{errRows.length} of {rows.length} rows with errors</span>
        <span style={{ flex: 1 }} />
        <label className="inline">
          <input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} /> only rows with errors
        </label>
        <button onClick={() => step(-1)}>◀ previous error</button>
        <button onClick={() => step(1)}>next error ▶</button>
      </div>
      <div className="cmp-strip" aria-label="Errors along the file">
        {bins.map((x, k) => (
          <i key={k} className={x.tone} onClick={() => (setOnlyErrors(false), setFilter(undefined), jump(x.first))} />
        ))}
      </div>
      <p className="muted cmp-legend">
        <span className="w-sub">wrong word</span> <span className="w-del">missed word</span> <span className="w-ins">extra word</span> {map.hasSpeakers && <span className="w-spk">right word, wrong speaker</span>} · amber strip = words, red = speakers. Click a speaker to hear it and name it.
      </p>
      {!map.hasSpeakers && <p className="info">1 side has no speakers. Only the words are compared.</p>}
      {map.hasSpeakers && (
        <details className="cmp-map" open>
          <summary>Speaker map: who is who</summary>
          <table className="versions">
            <thead>
              <tr>
                <th>Right ↓ / Left →</th>
                {leftSpeakers.map((s) => (
                  <th key={s}><span className="chip" style={chipStyle(color(s))}>{leftName(s)}</span></th>
                ))}
                <th>words</th><th>Problem</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(map.words).filter(Boolean).map((rs) => {
                const row = map.counts[rs] ?? {};
                const total = Object.values(row).reduce((s, c) => s + c, 0) || 1;
                return (
                  <tr key={rs}>
                    <th>
                      <span className={`chip${map.problem[rs] ? " bad" : ""}`} style={chipStyle(color(map.match[rs]))}>
                        {rightLabel(rs)}
                      </span>
                    </th>
                    {leftSpeakers.map((ls) => {
                      const share = (row[ls] ?? 0) / total;
                      const key = `${rs}|${ls}`;
                      return (
                        <td key={ls} className={`heat${filter === key ? " on" : ""}`} style={{ background: share ? `color-mix(in srgb, var(--accent) ${Math.round(share * 85)}%, transparent)` : undefined }}>
                          {row[ls] ? <button className="link" title="Show only the rows with these words" onClick={() => setFilter(filter === key ? undefined : key)}>{pct(share)}</button> : ""}
                        </td>
                      );
                    })}
                    <td>{map.words[rs]}</td>
                    <td>{map.problem[rs] ? PROBLEM_TEXT[map.problem[rs]] : "✓"}</td>
                  </tr>
                );
              })}
              <tr className="muted">
                <th>missed words</th>
                {leftSpeakers.map((ls) => <td key={ls}>{map.missed[ls] ?? ""}</td>)}
                <td>{Object.values(map.missed).reduce((s, c) => s + c, 0)}</td>
                <td>on the left side, not on the right</td>
              </tr>
            </tbody>
          </table>
          {filter && <button className="link" onClick={() => setFilter(undefined)}>Show all rows</button>}
        </details>
      )}
      <div className="cmp-rows">
        <div className="hd" /><div className="hd">Time</div><div className="hd">{label(a)}</div><div className="hd">{label(b)}</div>
        {shown.map(([r, i]) => {
          const tone = r.speakers ? "spk" : r.words ? "word" : "";
          const t = r.left?.start ?? r.right[0]?.start;
          return (
            <div key={i} className={`cmp-row ${tone}${cursor === i ? " cursor" : ""}${r.kind === "onlyB" ? " only" : ""}`}>
              <div className="gut" ref={(el) => void (rowEls.current[i] = el)}>{r.words + r.speakers || "✓"}</div>
              <div className="muted">{t !== undefined ? clock(String(t)) : ""}</div>
              <div>
                {r.left ? (
                  <>
                    {playBtn(`a:${i}`, r.left, `left row ${i + 1}`)}
                    {leftChip(r.left)}
                    {cells(r.left.cells)}
                  </>
                ) : (
                  <span className="muted">not on the left side</span>
                )}
              </div>
              <div>{rightSide(r, i)}</div>
            </div>
          );
        })}
        {shown.length === 0 && <p className="muted">No rows match.</p>}
      </div>
      {box && (
        <div className="cmp-box" style={{ left: box.x, top: box.y }} role="dialog" aria-label={`Speaker ${box.speaker}`}>
          <div className="row">
            <b>{box.side === "a" ? leftName(box.speaker) : rightName(box.speaker)}</b>
            <span className="muted">
              {box.side === "a" ? label(a) : label(b)} · {box.side === "b" ? map.words[box.speaker] : boxSegs.filter((s) => s.speaker === box.speaker).reduce((n, s) => n + s.cells.length, 0)} words · {mmss(boxSegs.filter((s) => s.speaker === box.speaker).reduce((n, s) => n + dur(s), 0))} speech
            </span>
            <span style={{ flex: 1 }} />
            <button className="link" aria-label="Close" onClick={() => setBox(undefined)}>✕</button>
          </div>
          <div>
            Samples:{" "}
            {boxSamples.length ? boxSamples.map((s, k) => <span key={k}>{playBtn(`box:${box.side}:${box.speaker}:${k}`, s, `sample ${k + 1}`)}</span>) : <span className="muted">no times</span>}
          </div>
          {shares.length > 0 && (
            <div>
              Words: {shares.sort((x, y) => y[1] - x[1]).map(([s, c]) => `${s} ${pct(c / (sharesTotal || 1))}`).join(" · ")}{" "}
              {box.side === "b" && map.problem[box.speaker] && <span className="chip bad">{map.problem[box.speaker]}</span>}
            </div>
          )}
          {boxError && <p className="error">{boxError}</p>}
          <div className="row">
            <label>
              {box.side === "a" && a === "ref" ? "Rename in the reference" : "Name"}
              <input value={name} maxLength={40} placeholder={box.speaker} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void saveBox()} />
            </label>
            <button className="primary" disabled={saving || !name.trim()} onClick={() => void saveBox()}>
              Save
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
