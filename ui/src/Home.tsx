import { platformLabel, type PlatformState, type StatusRow } from "./config";

const ORDER = ["vertex", "runpod", "modal", "cloudrun"];
const TEXT: Record<PlatformState, string> = { serving: "Serving", parked: "Parked", "not deployed": "Not deployed", off: "Out of service" };

/** Home page: 1 row per model, 1 column per platform, with the state of the model on that platform. */
export function Home({ rows, generatedAt }: { rows: StatusRow[]; generatedAt?: string }) {
  const ids = [...new Set(rows.flatMap((r) => r.platforms.map((p) => p.id)))].sort(
    (a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99),
  );
  return (
    <div className="home">
      <h1>Models and platforms</h1>
      {rows.length === 0 ? (
        <p className="muted">No status in models.json yet. Run ./scripts/ui-deploy.py.</p>
      ) : (
        <table className="status">
          <thead>
            <tr>
              <th>Model</th>
              <th>Type</th>
              <th>Version</th>
              {ids.map((id) => (
                <th key={id}>{platformLabel(id)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.tab ? <a href={`#/${encodeURIComponent(r.id)}`}>{r.title}</a> : r.title}</td>
                <td>{r.type}</td>
                <td><code>{r.version || "unknown"}</code></td>
                {ids.map((id) => {
                  const p = r.platforms.find((x) => x.id === id);
                  if (!p) return <td key={id} className="muted">-</td>;
                  const cell = <span className={`state ${p.state.replace(" ", "-")}`}>{TEXT[p.state]}</span>;
                  // The @platform part only when the tab has a platform picker (2 or more platforms).
                  const href = `#/${encodeURIComponent(r.id)}${r.platforms.length > 1 ? `@${encodeURIComponent(id)}` : ""}`;
                  return <td key={id}>{p.state === "serving" && r.tab ? <a href={href}>{cell}</a> : cell}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">
        Serving: the platform takes calls (it scales to 0, so the first call starts a GPU). Parked: the endpoint stays, but no worker can
        start (workers_max: 0 in deploy.yaml). Not deployed: the platform is on, but it has no model (run scripts/deploy.py deploy). Out of service: serve: false in deploy.yaml. -: the model does not use the platform.
        {generatedAt && ` Status from ${new Date(generatedAt).toLocaleString()} (scripts/ui-deploy.py).`}
      </p>
    </div>
  );
}
