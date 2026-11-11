import { useEffect, useState } from "react";
import { getApiKey, loadModels, setApiKey, type ModelConfig } from "./config";
import { PANELS } from "./panels";

const hashId = () => decodeURIComponent(location.hash.replace(/^#\/?/, ""));

export default function App() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [error, setError] = useState<string>();
  const [active, setActive] = useState(hashId());
  const [key, setKey] = useState(getApiKey());
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    loadModels().then(setModels, (e) => setError(String(e)));
    const onHash = () => setActive(hashId());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  const current = models.find((m) => m.id === active) ?? models[0];

  return (
    <>
      <header>
        <b className="brand">Model tests</b>
        <nav>
          {models.map((m) => (
            <a key={m.id} href={`#/${m.id}`} className={m === current ? "active" : ""}>
              {m.title}
            </a>
          ))}
        </nav>
        <label className="key">
          API key
          <input
            type={showKey ? "text" : "password"}
            value={key}
            placeholder="x-api-key (stays in this browser)"
            autoComplete="off"
            onChange={(e) => (setKey(e.target.value), setApiKey(e.target.value))}
          />
          <button onClick={() => setShowKey(!showKey)}>{showKey ? "Hide" : "Show"}</button>
          <button onClick={() => (setKey(""), setApiKey(""))}>Clear</button>
        </label>
      </header>
      <main>
        {error && <p className="error">{error}</p>}
        {!key && models.length > 0 && <p className="info">Enter the API key in the header (terraform output -raw api_key in infra/core).</p>}
        {/* Every panel stays mounted, so a tab keeps its chat and audio when you switch. */}
        {models.map((m) => {
          const Panel = PANELS[m.type];
          return (
            <div key={m.id} hidden={m !== current}>
              <h1>
                {m.title} <small>{m.type} · {m.model} · {m.base_url}</small>
              </h1>
              {Panel ? <Panel model={m} /> : <p className="error">No panel for type "{m.type}" yet. Add one with the model-ui skill.</p>}
            </div>
          );
        })}
      </main>
    </>
  );
}
