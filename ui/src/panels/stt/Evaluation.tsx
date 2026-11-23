import { pct, previousScore, vtime, type Score, type Summary } from "./lib";

interface Props {
  versions: Summary[];
  scores: Record<string, Score>;
  working?: string;
}

/** The Evaluation tab of the reference: 3 score cards for the working version, then 1 row per version. Lower is better. */
export default function Evaluation({ versions, scores, working }: Props) {
  const s = working ? scores[working] : undefined;
  const prev = working ? previousScore(versions, scores, working) : undefined;
  const all = Object.values(scores);
  const best = (k: "cpwer" | "wer") => (all.length ? Math.min(...all.map((x) => x[k])) : undefined);
  const card = (title: string, k: "cpwer" | "wer", hint: string) => (
    <div className="stt-scorecard" title={hint}>
      <div className="stt-pane-title">{title}</div>
      <b>{pct(s?.[k])}</b>
      <span className="muted">
        best {pct(best(k))}
        {prev ? ` · was ${pct(prev[k])}` : ""}
      </span>
    </div>
  );
  if (!versions.length) return <p className="muted">No versions yet. Use "New run".</p>;
  return (
    <div className="stt-eval">
      <p className="muted">{working ? `Version ${vtime(working)}. Lower is better.` : "Select a version."}</p>
      <div className="stt-scorecards">
        {card("cpWER", "cpwer", "text and speakers")}
        {card("WER", "wer", "text only")}
        <div className="stt-scorecard" title="speaker time, 0.25 s collar">
          <div className="stt-pane-title">DER</div>
          <b>{pct(s?.der?.der)}</b>
          <span className="muted">{s?.der ? `missed ${pct(s.der.missed)} · false alarm ${pct(s.der.false_alarm)} · confusion ${pct(s.der.confusion)}` : "no times: no DER"}</span>
        </div>
      </div>
      <table className="versions">
        <thead>
          <tr><th>Version</th><th>Label</th><th>cpWER</th><th>WER</th><th>DER</th><th>Speakers</th><th title="audio seconds per run second">Speed</th></tr>
        </thead>
        <tbody>
          {versions.map((v) => {
            const x = scores[v.id];
            return (
              <tr key={v.id} className={v.id === working ? "selected" : ""}>
                <td>{vtime(v.id)}</td>
                <td>{v.label || "-"}</td>
                <td><b>{pct(x?.cpwer)}</b></td>
                <td>{pct(x?.wer)}</td>
                <td>{pct(x?.der?.der)}</td>
                <td>{x ? `${x.hyp_speakers} of ${x.ref_speakers}` : v.speakers}</td>
                <td>{x?.speed ? `${x.speed}x` : "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
