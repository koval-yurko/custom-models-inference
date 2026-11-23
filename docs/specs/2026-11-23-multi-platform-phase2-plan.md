# Multi-platform phase 2 (UI platform picker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The test UI shows a platform picker on a model tab, and the panel calls the gateway path of the chosen platform (`/<platform><route>`).

**Architecture:** The `model` facade gets a `ui_platforms` output (1 entry per target, with the gateway URL plus `/<id>`). LLM-A puts it into its `ui` output. `scripts/ui-deploy.py` drops the platforms that are not deployed. In `ui/`, `config.ts` parses and chooses the platform, and `App.tsx` gives each panel a copy of the model with the `base_url` and `features.cold_start` of the chosen platform. The panel files do not change.

**Tech Stack:** Terraform >= 1.11 (`terraform test` with `mock_provider`), Python 3 standard library (`unittest`), React 19 + TypeScript + Vite, `vitest`.

**Spec:** `docs/specs/2026-11-22-multi-platform-design.md` (sections "UI", "Deploy script", "Phases" row 2). Phase 1 plan: `docs/specs/2026-11-22-multi-platform-phase1-plan.md` (done).

## Global Constraints

- The test UI keeps 1 tab per model. The panels do not change (`ui/src/panels/*.tsx` stay as they are).
- The picker shows only when a model has 2 or more platforms.
- The choice is kept per model in `localStorage` and in the hash as `#/<tab>@<platform>`. An STT link `#/<tab>/<file>` keeps working.
- The panel key stays the model id, so a chat is kept when the user switches platform.
- Retry on 429 when `cold_start` is `retry-429` or the old `vertex-429`. Every 30 s, at most 60 times, as today.
- `features.cold_start` moves into each platform entry (`platforms[].cold_start`) for a deployment on the facade. LLM-B, STT-A and TTS-A keep their `ui` output as it is.
- `models.json` entry: `base_url` = the URL of the default platform (`<gateway>/<first platform>`), `platforms` = list of `{ id, label, base_url, cold_start }` in the order of `local.platforms`.
- `ui-deploy.py` drops a platform entry when the platform says it is not deployed. It drops the tab when no entry is left.
- No provider key in `models.json` or the browser. Only the shared `x-api-key`, as today.
- Scripts: Python 3 standard library only. Each script loads `.env` itself. No `direnv exec` in front of a script.
- The agent does not run apply, deploy or test calls on real GCP. It verifies with `./scripts/check.py`, `terraform fmt -recursive -check`, `cd ui && npm test && npm run build`, and `verify-ui` against the mock.
- Docs prose in Simplified Technical English.

## Review Focus

1. A hash with a platform the model does not have (`#/llm-a@baseten` when Baseten is not deployed): the UI uses the stored choice or the first platform, and does not break. Test: `choosePlatform` in Task 2.
2. An STT file link (`#/stt-mock/<file>`, written by `Stt.tsx` without `@platform`) after the user picked `runpod`: the platform stays `runpod`, because the stored choice wins over "no platform in the hash". Test: `choosePlatform` in Task 2, plus the verify-ui feature in Task 5.
3. The default platform is not deployed, but another one is: the tab stays, and its `base_url` points to the first kept platform, not to the undeployed default. Test: `keep_deployed` in Task 4.
4. An old `models.json` entry without `platforms` (LLM-B, STT-A, TTS-A): no picker, the same `base_url` and `cold_start: "vertex-429"` retry as today. Tests: `parseModels`, `withPlatform` in Task 2, `call` in Task 3.
5. A `models.json` with a bad platform list (empty list, duplicate id, `http://` URL): `parseModels` shows a clear error, as it does for a bad `base_url` today. Test: `parseModels` in Task 2.

---

## File Structure

| File | Change |
|---|---|
| `infra/modules/model/outputs.tf`, `tests/model.tftest.hcl` | New output `ui_platforms` |
| `deployments/llm-a-gemma4-12b-vllm/outputs.tf`, `tests/gateway.tftest.hcl` | `ui` output gets `base_url` of the default platform and `platforms`; `features.cold_start` removed |
| `ui/src/config.ts`, `ui/src/lib.test.ts` | `Platform` type, `parseModels`, `parseHash`, `choosePlatform`, `withPlatform`, stored choice |
| `ui/src/api.ts` | `retriesOn429` |
| `ui/src/components.tsx`, `ui/src/App.tsx`, `ui/src/styles.css` | `PlatformPicker`, header line, hold note |
| `ui/mock-server.mjs`, `ui/public/models.mock.json`, `scripts/verify-ui.py` | Platform prefix in the mock, 2 or 3 mock platforms, mock URLs for the platforms |
| `scripts/ui-deploy.py`, `scripts/tests/test_ui_deploy.py`, `scripts/tests/test_verify_ui.py` | Drop undeployed platforms |
| `.claude/skills/model-ui/SKILL.md`, `.claude/skills/verify-ui/SKILL.md` + `features/platform-picker.md`, `docs/auth-and-ui.md`, `infra/README.md`, LLM-A README | Docs |

---

### Task 1: `ui_platforms` output in the facade, used by LLM-A

**Files:**
- Modify: `infra/modules/model/outputs.tf`, `infra/modules/model/tests/model.tftest.hcl`
- Modify: `deployments/llm-a-gemma4-12b-vllm/outputs.tf` (output `ui`), `deployments/llm-a-gemma4-12b-vllm/tests/gateway.tftest.hcl` (the run with the `ui` asserts)

**Interfaces:**
- Consumes: `local.targets` (phase 1; each target has `id`, `label`, `cold_start`), `module.gateway.gateway_url` (`https://<host>`, no trailing slash).
- Produces: `output "ui_platforms"`: `list(object({ id = string, label = string, base_url = string, cold_start = string }))` in the order of `var.platforms`. `base_url = "${gateway_url}/${id}"`.

- [ ] **Step 1: Write the failing tests**

In `model.tftest.hcl`, add:

```hcl
run "ui_platforms" {
  command = plan
  assert {
    condition     = length(output.ui_platforms) == 1 && output.ui_platforms[0].id == "vertex" && output.ui_platforms[0].label == "Vertex AI"
    error_message = "1 ui platform per target, in the order of platforms"
  }
  assert {
    condition     = output.ui_platforms[0].base_url == "${output.gateway_url}/vertex" && output.ui_platforms[0].cold_start == "retry-429"
    error_message = "base_url is the gateway URL plus /<id>; cold_start comes from the target"
  }
}
```

If `gateway_url` is unknown at plan in the mock, use `command = apply` (the other runs in the file show which one works).

In the LLM-A test, replace the assert "the ui output stays on the gateway root" with:

```hcl
  assert {
    condition     = output.ui.base_url == "${output.gateway_url}/vertex" && output.ui.id == "llm-a-gemma4"
    error_message = "the ui base_url is the default platform path"
  }
  assert {
    condition     = length(output.ui.platforms) == 1 && output.ui.platforms[0].id == "vertex" && !contains(keys(output.ui.features), "cold_start")
    error_message = "cold_start moves from features into each platform entry"
  }
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd infra/modules/model && terraform init -backend=false && terraform test` and the same in `deployments/llm-a-gemma4-12b-vllm`.
Expected: FAIL. `ui_platforms` is not declared; the LLM-A `ui` asserts fail.

- [ ] **Step 3: Implement**

- `infra/modules/model/outputs.tf`: `output "ui_platforms"` with the list from the Interfaces block. Description: "Platforms for the ui output of the deployment (scripts/ui-deploy.py -> models.json)."
- LLM-A `outputs.tf`, output `ui`: `base_url = module.model.ui_platforms[0].base_url`, new key `platforms = module.model.ui_platforms`, remove `cold_start` from `features` (keep `stream`, `max_tokens`, `max_context`). Update the comment on `features` so it says that `cold_start` is per platform.

- [ ] **Step 4: Run the tests to see them pass**

Run: `./scripts/check.py`
Expected: every line `ok`.

- [ ] **Step 5: Commit**

```bash
git add infra/modules/model deployments/llm-a-gemma4-12b-vllm
git commit -m "feat(model): ui_platforms output; LLM-A ui output lists its platforms"
```

---

### Task 2: Platforms in `config.ts`

**Files:**
- Modify: `ui/src/config.ts`, `ui/src/lib.test.ts`

**Interfaces:**
- Produces (all exported from `ui/src/config.ts`):
  - `interface Platform { id: string; label: string; base_url: string; cold_start?: string }`
  - `ModelConfig.platforms?: Platform[]`
  - `parseHash(hash: string): { tab: string; platform?: string; file?: string }`. Keys that have no value are left out (the old tests use `toEqual`).
  - `choosePlatform(model: ModelConfig, fromHash?: string, stored?: string): Platform | undefined`. `undefined` when the model has no platforms. Order: the hash id if the model has it, else the stored id if the model has it, else `platforms[0]`.
  - `withPlatform(model: ModelConfig, p?: Platform): ModelConfig`. Without `p`: the same object. With `p`: a copy with `base_url = p.base_url`, and `features.cold_start = p.cold_start` when `p.cold_start` is set.
  - `getPlatform(modelId: string): string | undefined` and `setPlatform(modelId: string, platformId: string): void`, with the `localStorage` key `model-test-ui.platform.<model id>`.

- [ ] **Step 1: Write the failing tests** in `lib.test.ts`

```ts
describe("parseModels platforms", () => {
  const p = (id: string, base_url = `https://gw/${id}/`) => ({ id, label: id.toUpperCase(), base_url, cold_start: "retry-429" });
  const ok = { id: "a", title: "A", type: "llm", base_url: "https://gw/vertex", model: "m" };
  it("keeps the platforms in order and trims each base_url", () => {
    const m = parseModels({ models: [{ ...ok, platforms: [p("vertex"), p("runpod")] }] })[0];
    expect(m.platforms?.map((x) => [x.id, x.base_url])).toEqual([["vertex", "https://gw/vertex"], ["runpod", "https://gw/runpod"]]);
  });
  it("rejects an empty list, a duplicate id and an http URL", () => {
    expect(() => parseModels({ models: [{ ...ok, platforms: [] }] })).toThrow(/models\[0\]\.platforms/);
    expect(() => parseModels({ models: [{ ...ok, platforms: [p("vertex"), p("vertex")] }] })).toThrow(/duplicate/);
    expect(() => parseModels({ models: [{ ...ok, platforms: [p("vertex", "http://x")] }] })).toThrow(/platforms\[0\]\.base_url/);
    expect(() => parseModels({ models: [{ ...ok, platforms: [{ id: "vertex", base_url: "https://gw" }] }] })).toThrow(/platforms\[0\]\.label/);
  });
  it("accepts an entry without platforms (old models.json)", () => {
    expect(parseModels({ models: [ok] })[0].platforms).toBeUndefined();
  });
});

describe("parseHash platform", () => {
  it("reads @<platform> and keeps the STT file link", () => {
    expect(parseHash("#/llm-a@runpod")).toEqual({ tab: "llm-a", platform: "runpod" });
    expect(parseHash("#/stt@vertex/f1")).toEqual({ tab: "stt", platform: "vertex", file: "f1" });
    expect(parseHash("#/stt/f1")).toEqual({ tab: "stt", file: "f1" });
    expect(parseHash("#/a@")).toEqual({ tab: "a" });
  });
});

describe("choosePlatform and withPlatform", () => {
  const V = { id: "vertex", label: "Vertex AI", base_url: "https://gw/vertex", cold_start: "retry-429" };
  const R = { id: "runpod", label: "Runpod", base_url: "https://gw/runpod", cold_start: "retry-429" };
  const m = { id: "a", title: "A", type: "llm", base_url: V.base_url, model: "x", features: { stream: true }, platforms: [V, R] };
  it("hash wins, then the stored choice, then the first platform", () => {
    expect(choosePlatform(m, "runpod", "vertex")).toBe(R);
    expect(choosePlatform(m, "baseten", "runpod")).toBe(R); // unknown hash id: not deployed
    expect(choosePlatform(m, undefined, "runpod")).toBe(R); // STT file link without @platform
    expect(choosePlatform(m, undefined, "gone")).toBe(V);
    expect(choosePlatform({ ...m, platforms: undefined })).toBeUndefined();
  });
  it("gives the panel the base_url and cold_start of the platform, and keeps the rest", () => {
    expect(withPlatform(m, R)).toMatchObject({ id: "a", base_url: R.base_url, features: { stream: true, cold_start: "retry-429" } });
    const old = { ...m, platforms: undefined, features: { cold_start: "vertex-429" } };
    expect(withPlatform(old, undefined)).toBe(old);
  });
});
```

Add `choosePlatform` and `withPlatform` to the import from `./config`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd ui && npm test`
Expected: FAIL. `choosePlatform` is not exported; the platform asserts fail.

- [ ] **Step 3: Implement** the Interfaces block in `config.ts`

`parseModels` checks `platforms` only when the key exists. Each entry needs a non-empty string `id`, `label` and `base_url`. Use the same URL rule as `base_url` (move the regex to one `const`). Error messages use the path `models[<i>].platforms[<j>].<key>`, and `models[<i>].platforms: duplicate id <id>`. `parseHash` splits the first segment at the first `@`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd ui && npm test`
Expected: PASS (the old `parseHash` and `parseModels` tests too).

- [ ] **Step 5: Commit**

```bash
git add ui/src/config.ts ui/src/lib.test.ts
git commit -m "feat(ui): platforms in models.json, @platform in the hash, platform choice"
```

---

### Task 3: Retry rule in `api.ts`

**Files:**
- Modify: `ui/src/api.ts`, `ui/src/lib.test.ts` (block `describe("call (Vertex 429 retry)")`)

**Interfaces:**
- Produces: `export const retriesOn429 = (coldStart: unknown): boolean` — true for `"retry-429"` and `"vertex-429"`, false for anything else (`"hold"`, `undefined`). `call()` uses it in place of `=== "vertex-429"`.

- [ ] **Step 1: Write the failing tests**

```ts
describe("retriesOn429", () => {
  it("retries for retry-429 and the old vertex-429 only", () => {
    expect([retriesOn429("retry-429"), retriesOn429("vertex-429"), retriesOn429("hold"), retriesOn429(undefined)]).toEqual([true, true, false, false]);
  });
});
```

In the `call` block, add one test with `features: { cold_start: "retry-429" }` that copies the existing "retries a real 429" test (fake timers, 429 then 200, `onRetry` called once with 1). Add one test with `cold_start: "hold"`: a 429 comes back at once, `fetch` is called 1 time, `onRetry` is not called.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd ui && npm test`
Expected: FAIL. `retriesOn429` is not exported; the `retry-429` test gets the 429 back.

- [ ] **Step 3: Implement** `retriesOn429` and use it in `call()`. Update the doc comment of `call` (Vertex AI and Runpod return 429 at 0 replicas).

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd ui && npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/api.ts ui/src/lib.test.ts
git commit -m "feat(ui): retry 429 for cold_start retry-429 and vertex-429"
```

---

### Task 4: `ui-deploy.py` drops undeployed platforms

**Files:**
- Modify: `scripts/ui-deploy.py`
- Create: `scripts/tests/test_ui_deploy.py`

**Interfaces:**
- Consumes: `deploy.step(target)` from `scripts/deploy.py` (phase 1: the post-apply module or `None`), the module function `deployed(d) -> bool`, and `terraform output -json targets`.
- Produces in `scripts/ui-deploy.py`:
  - `keep_deployed(entry: dict, deployed: dict[str, bool]) -> dict | None`. Pure. An entry without `platforms` comes back unchanged. Else it keeps the platforms with `deployed.get(id, True)`, in order, sets `base_url` to the first kept `base_url`, and returns `None` when none is left. It does not change the input dict.
  - `platform_deployed(d, targets: dict) -> dict[str, bool]`. For each target: `True` when `step(t)` is `None`, else `step(t).deployed(d)`. An exception or `SystemExit` gives `True` and a `warn` line (the same rule as `has_deployed_model` today: a failed check must not hide a deployed model).
  - `collect()`: an entry with `platforms` uses `keep_deployed(entry, platform_deployed(d, targets))`. It prints `skip <name>: no deployed platform (run scripts/deploy.py deploy <dir>)` for `None`, and `add  <name>: <base_url> (<ids>)` else. An entry without `platforms` keeps `has_deployed_model`.

- [ ] **Step 1: Write the failing tests** in `scripts/tests/test_ui_deploy.py` (load the script with `importlib`, as `test_deploy.py` does)

```python
E = {"id": "a", "base_url": "https://gw/vertex", "platforms": [
    {"id": "vertex", "base_url": "https://gw/vertex"}, {"id": "runpod", "base_url": "https://gw/runpod"}]}

class KeepDeployed(unittest.TestCase):
    def test_all_deployed(self):
        self.assertEqual(ui.keep_deployed(E, {"vertex": True, "runpod": True}), E)
    def test_default_gone_moves_base_url(self):
        out = ui.keep_deployed(E, {"vertex": False, "runpod": True})
        self.assertEqual((out["base_url"], [p["id"] for p in out["platforms"]]), ("https://gw/runpod", ["runpod"]))
        self.assertEqual(len(E["platforms"]), 2)  # input unchanged
    def test_none_left(self):
        self.assertIsNone(ui.keep_deployed(E, {"vertex": False, "runpod": False}))
    def test_old_entry_unchanged(self):
        old = {"id": "b", "base_url": "https://gw"}
        self.assertIs(ui.keep_deployed(old, {}), old)

class PlatformDeployed(unittest.TestCase):
    def test_no_post_apply_is_deployed_and_a_failed_check_keeps_it(self):
        # patch ui.deploy.step: vertex -> object whose deployed() raises SystemExit, runpod -> None
        ...  # assert result == {"vertex": True, "runpod": True}
```

Write the `PlatformDeployed` body with `unittest.mock.patch.object(ui.deploy, "step", ...)`. A second case: `deployed()` returns `False` gives `{"vertex": False}`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `python3 -m unittest discover -s scripts/tests -v`
Expected: FAIL. `keep_deployed` does not exist.

- [ ] **Step 3: Implement** the Interfaces block. Import `deploy` next to `platforms.vertex` (same `sys.path` line). Read `targets` with the same `terraform output -json` call that reads `ui`. Update the docstring: a platform is in the UI only when it is deployed.

- [ ] **Step 4: Run the tests to see them pass**

Run: `./scripts/check.py`
Expected: every line `ok`, with the new tests in "python tests (scripts)".

- [ ] **Step 5: Commit**

```bash
git add scripts/ui-deploy.py scripts/tests/test_ui_deploy.py
git commit -m "feat(scripts): ui-deploy keeps only the deployed platforms of a model"
```

---

### Task 5: Mock platforms and `verify-ui.py`

**Files:**
- Modify: `ui/mock-server.mjs`, `ui/public/models.mock.json`, `scripts/verify-ui.py`
- Create: `scripts/tests/test_verify_ui.py`

**Interfaces:**
- Produces:
  - Mock: a request path that starts with `/vertex/`, `/runpod/` or `/baseten/` loses that segment before routing (one line after the `OPTIONS` answer). Every existing route then works with and without a prefix.
  - `models.mock.json`: `llm-mock` gets `platforms` `vertex` (Vertex AI, `retry-429`), `runpod` (Runpod, `retry-429`) and `baseten` (Baseten, `hold`). `stt-mock` gets `vertex` and `runpod`. Each `base_url` is `http://localhost:5181/<id>`, and the top `base_url` is the first one. `features.cold_start` is removed from these 2 entries. `tts-mock` and `llm-routes-mock` stay without platforms (old format).
  - `scripts/verify-ui.py`: `point_to_mock(cfg: dict, mock: str) -> dict` sets every top `base_url` to `mock`, and every platform `base_url` to `f"{mock}/{id}"`. `up()` uses it. The doctor check "models.json points every tab to the mock" reads the top `base_url` and the platform URLs (all must start with `mock`). A new doctor check: `GET {mock}/runpod/v1/audio/voices` with the key answers 200.

- [ ] **Step 1: Write the failing test** `scripts/tests/test_verify_ui.py`

```python
def test_point_to_mock(self):
    cfg = {"models": [{"id": "a", "base_url": "http://localhost:5181/vertex",
                       "platforms": [{"id": "vertex", "base_url": "x"}, {"id": "runpod", "base_url": "y"}]},
                      {"id": "b", "base_url": "http://localhost:5181"}]}
    out = vu.point_to_mock(cfg, "http://127.0.0.1:9")
    self.assertEqual([m["base_url"] for m in out["models"]], ["http://127.0.0.1:9", "http://127.0.0.1:9"])
    self.assertEqual([p["base_url"] for p in out["models"][0]["platforms"]], ["http://127.0.0.1:9/vertex", "http://127.0.0.1:9/runpod"])
```

- [ ] **Step 2: Run it to see it fail**

Run: `python3 -m unittest discover -s scripts/tests -v`
Expected: FAIL. `point_to_mock` does not exist.

- [ ] **Step 3: Implement** the Interfaces block (mock, mock config, `verify-ui.py`).

- [ ] **Step 4: Run the checks**

Run: `python3 -m unittest discover -s scripts/tests -v`, then `./scripts/verify-ui.py up`, `./scripts/verify-ui.py doctor`, `./scripts/verify-ui.py down`.
Expected: tests PASS; `doctor` prints only `ok` lines, the new prefix check too.

- [ ] **Step 5: Commit**

```bash
git add ui/mock-server.mjs ui/public/models.mock.json scripts/verify-ui.py scripts/tests/test_verify_ui.py
git commit -m "feat(ui): mock answers on platform paths; verify-ui points platforms to the mock"
```

---

### Task 6: `PlatformPicker` in the app

**Files:**
- Modify: `ui/src/components.tsx`, `ui/src/App.tsx`, `ui/src/styles.css`
- Create: `.claude/skills/verify-ui/features/platform-picker.md`

**Interfaces:**
- Consumes: `parseHash`, `choosePlatform`, `withPlatform`, `getPlatform`, `setPlatform` (Task 2); the mock config (Task 5).
- Produces: `export function PlatformPicker(props: { platforms: Platform[]; value: string; onChange: (id: string) => void })` in `components.tsx`. One `<button>` per platform with its `label` and `aria-pressed` for the chosen one, inside `<div role="group" aria-label="Platform">`, with the text `Platform:` in front.

- [ ] **Step 1: Write the feature file** `.claude/skills/verify-ui/features/platform-picker.md`, in the format of `llm-chat.md`. Steps and the proof for each:
  1. Open `<ui_url>#/llm-mock`. The picker shows `Vertex AI`, `Runpod`, `Baseten`. `Vertex AI` is pressed. The header line ends with `Vertex AI`.
  2. Click `Runpod`. The hash is `#/llm-mock@runpod`. Send a chat message. `mock.log` has `POST /runpod/v1/chat/completions`.
  3. The chat history from step 2 is still there after a click on `Vertex AI` and back.
  4. Click `Baseten`. The hold note shows: "Baseten holds the request until a replica is ready. The first call can take several minutes."
  5. Reload the page with `#/llm-mock`. `Runpod` or `Baseten` (the last click) is still pressed (stored choice).
  6. Open `#/tts-mock`. No picker.
  7. Open `#/stt-mock`, click `Runpod`, transcribe a file and open it from the list (the hash becomes `#/stt-mock/<file id>`). `Runpod` stays pressed. `mock.log` has `/runpod/v1beta/...` lines.

- [ ] **Step 2: Run the feature to see it fail**

Run: `./scripts/verify-ui.py up`, then step 1 of the feature in the Paseo browser.
Expected: FAIL. There is no picker.

- [ ] **Step 3: Implement**

- `App.tsx`: keep `picks: Record<string, string>` state (start values from `getPlatform`). For each model: `chosen = choosePlatform(m, hashTab === m.id ? hashPlatform : undefined, picks[m.id])`. The panel gets `withPlatform(m, chosen)`, with `key={m.id}` as today. A picker click calls `setPlatform`, updates `picks`, and sets `location.hash = #/<id>@<platform>`. Read the platform from the hash in the existing `hashchange` handler.
- Header `<small>`: `type · model · <chosen label> · <chosen base_url>` when the model has platforms, else as today.
- Show `PlatformPicker` above the panel only when `m.platforms.length >= 2`.
- When `chosen.cold_start === "hold"`, show `<p className="info">{label} holds the request until a replica is ready. The first call can take several minutes.</p>` under the picker.
- `styles.css`: style the picker group like the existing header buttons; the pressed button uses the `.active` look of the tabs.

- [ ] **Step 4: Run the checks**

Run: `cd ui && npm test && npm run build`, then all 7 steps of the feature with `verify-ui` (proof in `.verify/ui/<run-id>/`), then `./scripts/verify-ui.py down`.
Expected: tests and build pass. Each step of the feature shows its proof. Also run the existing feature `llm-chat.md` once: it still passes.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components.tsx ui/src/App.tsx ui/src/styles.css .claude/skills/verify-ui/features/platform-picker.md
git commit -m "feat(ui): platform picker per model tab"
```

---

### Task 7: Docs

**Files:**
- Modify: `.claude/skills/model-ui/SKILL.md`, `.claude/skills/verify-ui/SKILL.md`, `docs/auth-and-ui.md`, `infra/README.md` (section "Test UI" and "Module: model (platforms)"), `deployments/llm-a-gemma4-12b-vllm/README.md`, `CLAUDE.md` (the "Test UI" paragraph)

- [ ] **Step 1: Update the docs**

- `model-ui` skill: the `ui` output schema gets `platforms` (from `module.model.ui_platforms`) and the `base_url` of the default platform. The `features` table: `cold_start` values `retry-429` (retry), `vertex-429` (old name, same rule), `hold` (no retry, hold note). For a deployment on the facade, `cold_start` is per platform. The picker shows with 2 or more platforms. The hash is `#/<tab>@<platform>`.
- `verify-ui` skill: list `platform-picker.md` and the mock platform prefix.
- `docs/auth-and-ui.md`: one short paragraph on the picker and the path prefix. If a diagram there shows the UI call path, add the `/<platform>` prefix to its edge label and run the render check of the `diagrams` skill.
- `infra/README.md`: `ui_platforms` in the output list of the `model` module; the "Test UI" section says that `ui-deploy.py` drops undeployed platforms.
- LLM-A README: after the apply of this change, run `./scripts/ui-deploy.py` (full: `ui/` changed). The tab calls `/vertex/v1/chat/completions` now. The picker shows only after a second platform (phase 3).
- `CLAUDE.md`: one sentence in the "Test UI" paragraph: a tab has a platform picker when the model has 2 or more deployed platforms.

- [ ] **Step 2: Run the checks**

Run: `./scripts/check.py && terraform fmt -recursive -check && (cd ui && npm test && npm run build)`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills docs infra/README.md deployments/llm-a-gemma4-12b-vllm/README.md CLAUDE.md
git commit -m "docs: UI platform picker (multi-platform phase 2)"
```

---

## What the user runs after this phase

Do these after the phase 1 apply. The `/vertex/` paths must answer first.

1. `cd deployments/llm-a-gemma4-12b-vllm && direnv exec . terraform plan`. Expected: only the `ui` output changes. No resource changes.
2. Apply. Then run `./scripts/ui-deploy.py` (a full build, because `ui/` changed).
3. Open the UI. The LLM-A tab has no picker (1 platform), and the header line shows `Vertex AI`. A chat call goes to `/vertex/v1/chat/completions`. A call starts a GPU replica (about $1.34 per hour).
