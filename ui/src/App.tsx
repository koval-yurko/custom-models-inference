import { useEffect, useState } from "react";
import { PlatformPicker } from "./components";
import { choosePlatform, getApiKey, hashPick, getPlatform, loadModels, parseHash, setApiKey, setPlatform, withPlatform, type ModelConfig, type StatusRow } from "./config";
import { Home } from "./Home";
import { PANELS } from "./panels";

export default function App() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [status, setStatus] = useState<StatusRow[]>([]);
  const [generatedAt, setGeneratedAt] = useState<string>();
  const [error, setError] = useState<string>();
  const [hash, setHash] = useState(parseHash(location.hash));
  const active = hash.tab;
  const [picks, setPicks] = useState<Record<string, string>>({}); // platform per model id, this session (else localStorage)
  const [key, setKey] = useState(getApiKey());
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    loadModels().then((c) => (setModels(c.models), setStatus(c.status), setGeneratedAt(c.generatedAt)), (e) => setError(String(e)));
    const onHash = () => setHash(parseHash(location.hash));
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  // A platform from a link is saved like a click, so the tab link and a reload keep it.
  useEffect(() => {
    const p = hashPick(models, hash);
    if (p && picks[p.model] !== p.platform) (setPlatform(p.model, p.platform), setPicks((x) => ({ ...x, [p.model]: p.platform })));
  }, [models, hash]); // eslint-disable-line react-hooks/exhaustive-deps

  // No tab in the hash (or #/home): the Home page. An unknown tab id falls back to the first tab.
  const home = active === "" || active === "home";
  const current = home ? undefined : (models.find((m) => m.id === active) ?? models[0]);
  const pick = (id: string, platform: string) => {
    setPlatform(id, platform);
    setPicks((p) => ({ ...p, [id]: platform }));
    location.hash = `#/${encodeURIComponent(id)}@${encodeURIComponent(platform)}`;
  };

  return (
    <>
      <header>
        <b className="brand">Model tests</b>
        <nav>
          <a href="#/" className={home ? "active" : ""}>
            Home
          </a>
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
        {home && <Home rows={status} generatedAt={generatedAt} />}
        {/* Every panel stays mounted, so a tab keeps its chat and audio when you switch. */}
        {models.map((m) => {
          const Panel = PANELS[m.type];
          // The hash platform counts only for its own tab; a link without @platform (STT file link) keeps the stored choice.
          const chosen = choosePlatform(m, hash.tab === m.id ? hash.platform : undefined, picks[m.id] ?? getPlatform(m.id));
          const model = withPlatform(m, chosen);
          return (
            <div key={m.id} hidden={m !== current}>
              <h1>
                {m.title} <small>{m.type} · {m.model} · {chosen ? `${chosen.label} · ` : ""}{model.base_url}</small>
              </h1>
              {chosen && m.platforms!.length >= 2 && <PlatformPicker platforms={m.platforms!} value={chosen.id} onChange={(p) => pick(m.id, p)} />}
              {chosen?.cold_start === "hold" && (
                <p className="info">{chosen.label} holds the request until a replica is ready. The first call can take several minutes; the chat shows the wait and sends again after a gateway time limit.</p>
              )}
              {/* key stays the model id, so a chat is kept when the user switches platform */}
              {Panel ? <Panel model={model} /> : <p className="error">No panel for type "{m.type}" yet. Add one with the model-ui skill.</p>}
            </div>
          );
        })}
      </main>
    </>
  );
}
