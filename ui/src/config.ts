// models.json: written by scripts/ui-deploy.py from the `ui` Terraform output of each deployment.
// Schema: .claude/skills/model-ui/SKILL.md.

export interface ModelConfig {
  id: string;
  title: string;
  type: string; // "llm" | "tts" | "stt" | ... (panels/index.ts maps it to a panel)
  base_url: string;
  model: string;
  features: Record<string, unknown>;
}

export function parseModels(json: unknown): ModelConfig[] {
  const list = (json as { models?: unknown })?.models;
  if (!Array.isArray(list)) throw new Error('models.json must be {"models": [...]}');
  return list.map((m, i) => {
    for (const k of ["id", "title", "type", "base_url", "model"]) {
      if (typeof m?.[k] !== "string" || !m[k]) throw new Error(`models.json: models[${i}].${k} must be a non-empty string`);
    }
    // http only for a local mock server (dev).
    if (!/^(https:\/\/|http:\/\/(localhost|127\.0\.0\.1)[:/])/.test(m.base_url))
      throw new Error(`models.json: models[${i}].base_url must start with https:// (or http://localhost for a mock)`);
    return { ...m, base_url: m.base_url.replace(/\/+$/, ""), features: m.features ?? {} } as ModelConfig;
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
