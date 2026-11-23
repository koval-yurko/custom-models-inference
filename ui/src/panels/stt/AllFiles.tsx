import { pct, type SetupRow } from "./lib";

/** The All files view: mean scores per setup over the files with a reference (GET /v1beta/scores). */
export default function AllFiles({ setups }: { setups: SetupRow[] }) {
  return (
    <div className="stt-allfiles">
      <h2>Accuracy per setup</h2>
      {setups.length === 0 ? (
        <p className="muted">Add a reference to a file to get scores.</p>
      ) : (
        <>
          <p className="muted">Mean over the versions of files with a reference. Lower is better.</p>
          <table className="versions">
            <thead>
              <tr><th>Setup</th><th>Files</th><th>Versions</th><th title="text and speakers">cpWER</th><th title="text only">WER</th><th title="speaker time, 0.25 s collar">DER</th></tr>
            </thead>
            <tbody>
              {setups.map((r) => (
                <tr key={r.setup}>
                  <td>{r.setup}</td><td>{r.files}</td><td>{r.versions}</td><td><b>{pct(r.cpwer)}</b></td><td>{pct(r.wer)}</td><td>{pct(r.der)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
