interface Props {
  time: number;
  duration: number;
  playing: boolean;
  rate: number;
  follow: boolean;
  onToggle: () => void;
  onSeek: (t: number) => void;
  onRate: (r: number) => void;
  onFollow: (f: boolean) => void;
}

const RATES = [1, 1.25, 1.5, 2];
const mmss = (s: number) => (Number.isFinite(s) ? `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "--:--");

/** The sticky player at the top of the work area. It drives the 1 <audio> element of the panel. */
export default function Player({ time, duration, playing, rate, follow, onToggle, onSeek, onRate, onFollow }: Props) {
  return (
    <div className="stt-player">
      <button aria-label={playing ? "Pause" : "Play"} onClick={onToggle}>
        {playing ? "❚❚" : "▶"}
      </button>
      <span className="muted">
        {mmss(time)} / {mmss(duration)}
      </span>
      <input type="range" aria-label="Position" min={0} max={Number.isFinite(duration) && duration > 0 ? duration : 0} step={0.1} value={time} onChange={(e) => onSeek(Number(e.target.value))} />
      <select aria-label="Speed" value={rate} onChange={(e) => onRate(Number(e.target.value))}>
        {RATES.map((r) => (
          <option key={r} value={r}>
            {r}×
          </option>
        ))}
      </select>
      <label className="inline">
        <input type="checkbox" checked={follow} onChange={(e) => onFollow(e.target.checked)} /> follow
      </label>
    </div>
  );
}
