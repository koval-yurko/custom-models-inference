import { useEffect, useRef, useState } from "react";

export interface Ask {
  title: string;
  text: string;
  action: string; // the label of the red button
  run: () => Promise<void>;
}

/** A modal confirm box (native <dialog>: Escape and the Cancel button close it). It stays open and shows the error when run fails. */
export default function Confirm({ ask, onClose }: { ask: Ask; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => ref.current?.showModal(), []);
  const ok = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await ask.run();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  return (
    <dialog ref={ref} className="confirm" onClose={onClose} onCancel={(e) => busy && e.preventDefault()}>
      <h3>{ask.title}</h3>
      <p>{ask.text}</p>
      <p className="muted">There is no undo.</p>
      {error && <p className="error">{error}</p>}
      <div className="row">
        <span style={{ flex: 1 }} />
        <button autoFocus disabled={busy} onClick={onClose}>
          Cancel
        </button>
        <button className="danger" disabled={busy} onClick={() => void ok()}>
          {busy ? "Deleting…" : ask.action}
        </button>
      </div>
    </dialog>
  );
}
