// models.json: written by scripts/ui-deploy.py from the `ui` Terraform output of each deployment.
// Schema: .claude/skills/model-ui/SKILL.md.

/** One platform of a model (Vertex AI, Runpod): the gateway path /<id> and its cold-start rule. */
export interface Platform {
  id: string;
  label: string;
  base_url: string;
  cold_start?: string; // "retry-429" | "vertex-429" | "hold"
}

export interface ModelConfig {
  id: string;
  title: string;
  type: string; // "llm" | "tts" | "stt" | ... (panels/index.ts maps it to a panel)
  base_url: string;
  model: string;
  features: Record<string, unknown>;
  platforms?: Platform[]; // only for a deployment on infra/modules/model; the first is the default
}

// http only for a local mock server (dev).
const URL_OK = /^(https:\/\/|http:\/\/(localhost|127\.0\.0\.1)[:/])/;
const trim = (u: string) => u.replace(/\/+$/, "");

function parsePlatforms(list: unknown, i: number): Platform[] {
  const at = `models.json: models[${i}].platforms`;
  if (!Array.isArray(list) || list.length === 0) throw new Error(`${at} must be a non-empty list`);
  const seen = new Set<string>();
  return list.map((p, j) => {
    for (const k of ["id", "label", "base_url"]) {
      if (typeof p?.[k] !== "string" || !p[k]) throw new Error(`${at}[${j}].${k} must be a non-empty string`);
    }
    if (!URL_OK.test(p.base_url)) throw new Error(`${at}[${j}].base_url must start with https:// (or http://localhost for a mock)`);
    if (seen.has(p.id)) throw new Error(`${at}: duplicate id ${p.id}`);
    seen.add(p.id);
    return { ...p, base_url: trim(p.base_url) } as Platform;
  });
}

export function parseModels(json: unknown): ModelConfig[] {
  const list = (json as { models?: unknown })?.models;
  if (!Array.isArray(list)) throw new Error('models.json must be {"models": [...]}');
  return list.map((m, i) => {
    for (const k of ["id", "title", "type", "base_url", "model"]) {
      if (typeof m?.[k] !== "string" || !m[k]) throw new Error(`models.json: models[${i}].${k} must be a non-empty string`);
    }
    if (!URL_OK.test(m.base_url))
      throw new Error(`models.json: models[${i}].base_url must start with https:// (or http://localhost for a mock)`);
    const platforms = "platforms" in m ? { platforms: parsePlatforms(m.platforms, i) } : {};
    return { ...m, base_url: trim(m.base_url), features: m.features ?? {}, ...platforms } as ModelConfig;
  });
}

export async function loadModels(): Promise<ModelConfig[]> {
  const r = await fetch("models.json", { cache: "no-store" });
  if (!r.ok) throw new Error(`models.json: HTTP ${r.status}. Run scripts/ui-deploy.py (or --local for dev).`);
  return parseModels(await r.json());
}

const KEY = "model-test-ui.api-key";
export const getApiKey = () => localStorage.getItem(KEY) ?? "";
export const setApiKey = (v: string) => (v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY));

/** "#/<tab>[@<platform>][/<file id>]" -> the tab id, the optional platform id and the optional file id (STT history links). */
export function parseHash(hash: string): { tab: string; platform?: string; file?: string } {
  const [first = "", file] = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const at = first.indexOf("@");
  const tab = at < 0 ? first : first.slice(0, at);
  const platform = at < 0 ? "" : first.slice(at + 1);
  return { tab, ...(platform ? { platform } : {}), ...(file ? { file } : {}) };
}

/** The platform the tab calls: the hash id if the model has it, else the stored id if it has it, else the first. */
export function choosePlatform(model: ModelConfig, fromHash?: string, stored?: string): Platform | undefined {
  const ps = model.platforms;
  if (!ps?.length) return undefined;
  return ps.find((p) => p.id === fromHash) ?? ps.find((p) => p.id === stored) ?? ps[0];
}

/** A platform that a link (#/<tab>@<platform>) chose and the model has: App saves it, so the tab link keeps it. */
export function hashPick(models: ModelConfig[], hash: { tab: string; platform?: string }): { model: string; platform: string } | undefined {
  const m = models.find((x) => x.id === hash.tab);
  return hash.platform && m?.platforms?.some((p) => p.id === hash.platform) ? { model: m.id, platform: hash.platform } : undefined;
}

/** The model as the panel sees it: base_url and cold_start of the chosen platform. */
export function withPlatform(model: ModelConfig, p?: Platform): ModelConfig {
  if (!p) return model;
  const features = { ...model.features, platform_label: p.label, ...(p.cold_start && { cold_start: p.cold_start }) };
  return { ...model, base_url: p.base_url, features };
}

const platformKey = (modelId: string) => `model-test-ui.platform.${modelId}`;
export const getPlatform = (modelId: string) => localStorage.getItem(platformKey(modelId)) ?? undefined;
export const setPlatform = (modelId: string, platformId: string) => localStorage.setItem(platformKey(modelId), platformId);
