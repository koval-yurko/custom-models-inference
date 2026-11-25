import { useEffect, useState } from "react";
import { LANGS, pct, refSummary, scoreTone, setupShort, vtime, type Reference, type Score, type Summary } from "./lib";

export interface NewRun { lang: string; diarize: boolean; label: string }

interface Props {
  versions: Summary[];
  scores: Record<string, Score>;
  reference?: Reference;
  row: string; // "ref" or a version id
  ticked: string[];
  run: { busy: string; startedAt?: number; error?: string };
  newRun: NewRun;
  onNewRun: (r: NewRun) => void;
  onSelect: (row: string) => void;
  onTick: (id: string) => void;
  onRun: () => void;
  onStop: () => void;
  onDelete: (row: string) => void; // "ref" or a version id
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** Column 2: the pinned reference row, the New run box, the run state and 1 card per version (newest first). */
export default function History({ versions, scores, reference, row, ticked, run, newRun, onNewRun, onSelect, onTick, onRun, onStop, onDelete }: Props) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!run.startedAt) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [run.startedAt]);
  const sum = reference && refSummary(reference);
  return (
    <div className="stt-history">
      <div className="stt-del-wrap">
      <button className={`stt-card stt-ref${reference ? "" : " ghost"}${row === "ref" ? " selected" : ""}`} onClick={() => onSelect("ref")}>
        {sum ? (
          <>
            <b>📌 Reference</b>
            <span className="muted">
              {sum.turns} turns · {sum.speakers.length} speakers · {sum.timed ? "times ✓" : "no times: no DER"}
            </span>
          </>
        ) : (
          <span>
            📌 ＋ Add reference <span className="muted">(optional: gives scores)</span>
          </span>
        )}
      </button>
      {reference && (
        <button className="stt-del" aria-label="Delete the reference" title="Delete the reference" onClick={() => onDelete("ref")}>
          🗑
        </button>
      )}
      </div>
      <div className="stt-newrun">
        <button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
          <b>＋ New run</b> {open ? "▾" : "▸"}
        </button>
        {open && (
          <div className="stt-newrun-form">
            <label>
              Language
              <select value={newRun.lang} onChange={(e) => onNewRun({ ...newRun, lang: e.target.value })}>
                <option value="">auto (detect)</option>
                {LANGS.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
            </label>
            <label className="inline">
              <input type="checkbox" checked={newRun.diarize} onChange={(e) => onNewRun({ ...newRun, diarize: e.target.checked })} /> Speakers
            </label>
            <label>
              Label
              <input value={newRun.label} maxLength={200} placeholder="for example: after tuning" onChange={(e) => onNewRun({ ...newRun, label: e.target.value })} />
            </label>
            <button className="primary" disabled={!!run.busy} onClick={onRun}>
              Transcribe
            </button>
          </div>
        )}
      </div>
      {(run.busy || run.error) && (
        <div className={`stt-running${run.error ? " failed" : ""}`}>
          {run.error ? (
            <span>Last run failed. See the error above.</span>
          ) : (
            <>
              <span>
                {run.busy} {run.startedAt ? mmss((now - run.startedAt) / 1000) : ""}
              </span>
              <button onClick={onStop}>Stop</button>
            </>
          )}
        </div>
      )}
      {versions.map((v) => {
        const s = scores[v.id];
        return (
          <div key={v.id} className={`stt-card stt-version${row === v.id ? " selected" : ""}`} onClick={() => onSelect(v.id)}>
            <div>
              <input type="checkbox" aria-label={`Compare ${vtime(v.id)}`} checked={ticked.includes(v.id)} onClick={(e) => e.stopPropagation()} onChange={() => onTick(v.id)} />{" "}
              <button className="link" onClick={() => onSelect(v.id)}>
                <b>{vtime(v.id)}</b>
              </button>{" "}
              {s && <span className={`chip ${scoreTone(s.cpwer)}`}>cpWER {pct(s.cpwer)}</span>}
              <button className="stt-del" aria-label={`Delete version ${vtime(v.id)}`} title="Delete this version" onClick={(e) => (e.stopPropagation(), onDelete(v.id))}>
                🗑
              </button>
            </div>
            <span className="muted" title={v.setup ? JSON.stringify(v.setup) : "a version made before the setup record"}>
              {v.label || "no label"} · {setupShort(v.setup)} · {v.speakers} spk · {v.run_seconds} s
            </span>
          </div>
        );
      })}
    </div>
  );
}
