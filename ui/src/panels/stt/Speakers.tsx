import { useEffect, useState } from "react";
import { COLORS, groupTurns, namesBody, refSummary, speechTime, vtime, words, type Names, type Reference, type Score, type Version } from "./lib";

interface Props {
  reference: Reference;
  version?: Version; // the working version
  score?: Score;
  onRenameRef: (renames: [string, string][]) => Promise<void>;
  onSaveNames: (n: Names) => Promise<void>;
  onApplyAll: (source: { names: Names; mapping: Record<string, string> }) => Promise<void>;
  onPlayFirst: (label: string) => void;
}

const mmss = (s: number | null) => (s == null ? "–" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);

/** The Speakers tab: the reference speakers (rename in the reference) and the labels of the working version (names). */
export default function Speakers({ reference, version, score, onRenameRef, onSaveNames, onApplyAll, onPlayFirst }: Props) {
  const ids = refSummary(reference).speakers;
  const time = speechTime(reference);
  const [refDraft, setRefDraft] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<Names>(version?.names ?? {});
  const [busy, setBusy] = useState(false);
  useEffect(() => setRefDraft(Object.fromEntries(ids.map((id) => [id, id]))), [ids.join("\n")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setDraft(version?.names ?? {}), [version?.id, version?.names]);
  const labels = version ? [...new Set(groupTurns(words(version)).map((g) => g.speaker))].filter((s) => /^spk_\d{1,2}$/.test(s)) : [];
  const mapping = score?.mapping ?? {};
  const renames = ids.map((id) => [id, (refDraft[id] ?? id).trim()] as [string, string]).filter(([a, b]) => b && a !== b);
  const wrap = (f: () => Promise<void>) => (setBusy(true), f().finally(() => setBusy(false)));
  return (
    <div className="stt-speakers">
      <div>
        <div className="stt-pane-title">Reference speakers</div>
        <table className="versions">
          <thead>
            <tr><th>ID</th><th>Name</th><th>Speech</th></tr>
          </thead>
          <tbody>
            {ids.map((id) => (
              <tr key={id}>
                <td>{id}</td>
                <td>
                  <input aria-label={`Reference name of ${id}`} value={refDraft[id] ?? id} maxLength={40} onChange={(e) => setRefDraft({ ...refDraft, [id]: e.target.value })} />
                </td>
                <td>{mmss(time[id])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="primary" disabled={busy || !renames.length} onClick={() => void wrap(() => onRenameRef(renames))}>
          Rename in reference
        </button>
      </div>
      <div>
        <div className="stt-pane-title">{version ? `Version ${vtime(version.id)}` : "Version"}</div>
        {!version ? (
          <p className="muted">Select a version.</p>
        ) : !labels.length ? (
          <p className="muted">This version has no speaker labels.</p>
        ) : (
          <table className="versions">
            <thead>
              <tr><th>Label</th><th>Match</th><th>Name</th><th></th></tr>
            </thead>
            <tbody>
              {labels.map((l, i) => (
                <tr key={l}>
                  <td style={{ color: COLORS[i % COLORS.length], fontWeight: 600 }}>{l}</td>
                  <td>{mapping[l] ?? <span className="chip warn">no match</span>}</td>
                  <td>
                    <input aria-label={`Name of ${l}`} value={draft[l] ?? ""} placeholder={l} maxLength={40} onChange={(e) => setDraft({ ...draft, [l]: e.target.value })} />
                  </td>
                  <td>
                    <button className="play" aria-label={`Play ${l}`} onClick={() => onPlayFirst(l)}>
                      ▶
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row">
          <button disabled={busy || !labels.length || !score} onClick={() => setDraft({ ...Object.fromEntries(labels.filter((l) => mapping[l]).map((l) => [l, mapping[l]])), ...namesBody(draft) })}>
            Use the matches
          </button>
          <button disabled={busy || !labels.length || !score} onClick={() => void wrap(() => onApplyAll({ names: namesBody(draft), mapping }))}>
            Apply to all versions
          </button>
          <button className="primary" disabled={busy || !labels.length} onClick={() => void wrap(() => onSaveNames(namesBody(draft)))}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
