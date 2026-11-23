import { useState } from "react";
import { pct, when, type FileRow } from "./lib";

interface Props {
  files: FileRow[];
  selected?: string; // a file id, or "all" for the All files view
  best: Record<string, number>;
  busy: boolean;
  onOpen: (id: string) => void;
  onAll: () => void;
  onUpload: (f: File) => void;
  onRefresh: () => void;
}

/** Column 1: the All files row, the drop zone, a search field and 1 card per file. */
export default function Files({ files, selected, best, busy, onOpen, onAll, onUpload, onRefresh }: Props) {
  const [q, setQ] = useState("");
  const [over, setOver] = useState(false);
  const [open, setOpen] = useState(false); // narrow screens: the full list shows only after "Change file"
  const shown = files.filter((f) => f.name.toLowerCase().includes(q.trim().toLowerCase()));
  const pick = (f?: File) => f && !busy && onUpload(f);
  return (
    <div className={`stt-files${open ? " open" : ""}`}>
      <div className="stt-head">
        <b>Files</b>
        <button onClick={onRefresh}>Refresh</button>
        <button className="stt-change" onClick={() => setOpen(!open)}>
          {open ? "Hide files" : "Change file"}
        </button>
      </div>
      <button className={`stt-card stt-all${selected === "all" ? " selected" : ""}`} onClick={onAll}>
        📊 All files: scores
      </button>
      <label
        className={`stt-drop${over ? " over" : ""}${busy ? " busy" : ""}`}
        onDragOver={(e) => (e.preventDefault(), setOver(true))}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => (e.preventDefault(), setOver(false), pick(e.dataTransfer.files[0]))}
      >
        ⬆ Drop an audio file or click
        <span className="muted">up to 500 MB, kept for new runs</span>
        <input type="file" aria-label="Upload a file" accept="audio/*,.m4a,.webm" className="sr-only" disabled={busy} onChange={(e) => (pick(e.target.files?.[0]), (e.target.value = ""))} />
      </label>
      <input className="stt-search" aria-label="Search files" placeholder="Search files" value={q} onChange={(e) => setQ(e.target.value)} />
      {files.length === 0 && <p className="muted">No files yet.</p>}
      {shown.map((f) => (
        <button key={f.id} className={`stt-card${f.id === selected ? " selected" : ""}`} onClick={() => (setOpen(false), onOpen(f.id))}>
          <b>{f.name}</b>
          <span className="muted">
            {(f.size_bytes / 1e6).toFixed(1)} MB · {f.versions} version{f.versions === 1 ? "" : "s"} · {when(f.created)}
          </span>
          <span>
            {f.reference ? <span className="chip ok">✓ reference</span> : <span className="chip">no reference</span>}
            {best[f.id] !== undefined && <span className="chip">best {pct(best[f.id])}</span>}
          </span>
        </button>
      ))}
    </div>
  );
}
