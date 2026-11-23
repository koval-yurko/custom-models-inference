import { useEffect, useRef, useState } from "react";
import { COLORS, clock, groupTurns, namesBody, nearestTurn, speakerName, vtime, words, type Names, type Version } from "./lib";

interface Props {
  v: Version;
  time: number; // the audio time, in seconds
  active: boolean; // the audio plays
  playingTurn?: number; // the turn that ▶ plays now (only this turn, then stop)
  follow: boolean;
  editNames: boolean; // no reference: rename here; with a reference the Speakers tab does it
  onPlayTurn: (turn: number, start: number, end: number) => void;
  onSeek: (t: number) => void;
  onNames: (n: Names) => Promise<void>;
  onRenameLink: () => void;
}

/** The turns of 1 version: ▶, start time (click to seek), speaker and text. The turn at the audio time has a highlight. */
export default function Transcript({ v, time, active, playingTurn, follow, editNames, onPlayTurn, onSeek, onNames, onRenameLink }: Props) {
  const groups = groupTurns(words(v));
  const speakers = [...new Set(groups.map((g) => g.speaker))];
  const labels = speakers.filter(Boolean);
  const [draft, setDraft] = useState<Names>(v.names ?? {});
  const [saving, setSaving] = useState(false);
  useEffect(() => setDraft(v.names ?? {}), [v.names]);
  const color = (spk: string) => COLORS[speakers.indexOf(spk) % COLORS.length];
  const save = () => (setSaving(true), onNames(namesBody(draft)).finally(() => setSaving(false)));
  const current = active ? nearestTurn(groups.map((g) => parseFloat(g.start)), time) : -1;
  const rows = useRef<(HTMLDivElement | null)[]>([]);
  useEffect(() => {
    if (follow && current >= 0) rows.current[current]?.scrollIntoView({ block: "nearest" });
  }, [follow, current]);
  return (
    <div className="transcript">
      <p className="muted">
        {vtime(v.id)} · image {v.image_tag} · {v.label || "no label"}
      </p>
      {labels.length > 0 &&
        (editNames ? (
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
        ) : (
          <button className="link" onClick={onRenameLink}>
            Rename speakers
          </button>
        ))}
      {groups.length === 0 && <p>{v.response.output_text || "(no speech)"}</p>}
      {groups.map((g, i) => (
        <div key={i} ref={(el) => void (rows.current[i] = el)} className={current === i || playingTurn === i ? "turn playing" : "turn"}>
          <button className="play" aria-label={`${playingTurn === i ? "Stop" : "Play"} turn ${i + 1}`} onClick={() => onPlayTurn(i, parseFloat(g.start), parseFloat(g.end))}>
            {playingTurn === i ? "■" : "▶"}
          </button>
          <button className="link time" aria-label={`Go to ${clock(g.start)}`} onClick={() => onSeek(parseFloat(g.start))}>
            {clock(g.start)}
          </button>
          <span>
            <span style={{ color: color(g.speaker), fontWeight: 600 }}>{speakerName(v.names, g.speaker)}</span> {g.text}
          </span>
        </div>
      ))}
    </div>
  );
}
