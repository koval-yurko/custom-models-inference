# Multi-platform phase 3 (Runpod) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM-A runs on Vertex AI and on Runpod at the same time. A call to `<gateway>/runpod/v1/chat/completions` goes through the same gateway, API key and CORS proxy to a Runpod load balancing endpoint that scales to 0.

**Architecture:** A new adapter `infra/modules/platform-runpod` turns the model spec into 1 `runpod_template` and 1 `runpod_serverless_endpoint`, and gives the common `target` output. The `model` facade calls it with `count` and gives the proxy the Runpod key as a secret env var. `infra/core` stores the key in Secret Manager (write-only). The proxy maps the Runpod "no workers available" answer to HTTP 429, so the UI retry rule from phase 2 works without a change.

**Tech Stack:** Terraform >= 1.11 (`terraform test` with `mock_provider`), provider `runpod/runpod ~> 2.0` (2.0.0 checked on 2026-11-23 with `terraform providers schema`), Python 3 standard library (`unittest`).

**Spec:** `docs/specs/2026-11-22-multi-platform-design.md` (sections "Adapter interface", "What each adapter does", "CORS proxy", "Secrets and keys", "Phases" row 3, "Open points"). Phase 1 plan: `docs/specs/2026-11-22-multi-platform-phase1-plan.md`. Phase 2 plan: `docs/specs/2026-11-23-multi-platform-phase2-plan.md`.

## Global Constraints

- One adapter per platform. No copied gateway, proxy or deploy code for Runpod. No code outside the adapter checks the platform id, except the proxy (credential and 429 match) and `deploy.py` (post-apply step).
- `workers_min = 0` on every endpoint. `max_replicas` stays 1.
- The Runpod API key never goes into git, `models.json`, the browser or a Terraform state. `infra/core` writes it with a write-only argument (`secret_data_wo`), like `hf-token`. HCP workspaces get it as a sensitive env var.
- The proxy reads the key from env `RUNPOD_API_KEY` (Secret Manager secret `runpod-api-key`) and sends `Authorization: Bearer <key>`. This code exists since phase 1.
- Runpod target: `id = "runpod"`, `label = "Runpod"`, `url = request_urls.base`, `append_path = true`, `auth = "runpod"`, `cold_start = "retry-429"`, `deadline = 300`, `post_apply = null`.
- `{model}` on Runpod = `spec.weights.hf_repo`. The adapter adds `--revision=<spec.weights.revision>`. `HF_HUB_OFFLINE = "0"`.
- Health: env `PORT` and `PORT_HEALTH` = `spec.port`, `HEALTH_CHECK_PATH` = `spec.health_route`.
- Defaults: `gpu_pools = ["AMPERE_24"]`, `excluded_types = []`, `scaling_value = 4`, container disk 60 GB, `flashboot = "FLASHBOOT"`, any cloud type, no data center pin.
- Runpod flags must work on every GPU type in the pools. `AMPERE_24` (L4, A5000, 3090) has no native FP8, so LLM-A gets no `--kv-cache-dtype=fp8` on Runpod.
- Scripts: Python 3 standard library only. Each script loads `.env` itself. No `direnv exec` in front of a script.
- The agent does not run apply, deploy or test calls on real GCP or Runpod. It verifies with `./scripts/check.py` and `terraform fmt -recursive -check`.
- Docs prose in Simplified Technical English.

## Review Focus

1. The real Runpod answer at 0 workers has another status or body than the match expects: the UI then shows the raw error and does not retry. The match is in 1 function (`cold_answer`), and the user records the real answer at the first cold call. Test: `cold_answer` in Task 3, plus the user step "Record the cold answer".
2. A good Runpod answer (200, SSE stream) must stream as before. The proxy may read the full body only for an error status of a Runpod target. Test: `cold_answer` returns False for 200 in Task 3; the reviewer checks that `forward` reads the body only when `auth == "runpod"` and `status >= 400`.
3. A model with `weights` but without `weights.revision` on Runpod: the plan fails with a clear message, so 2 platforms never load different weights. Test: `revision_required` in Task 1.
4. A model on Runpod only (`platforms = ["runpod"]`): no `aiplatform.user` binding, `vertex` outputs are null, the proxy default is `runpod`, and the proxy gets the Runpod secret. Test: `runpod_only` in Task 2.
5. Runpod takes `args` as 1 string, not a list. An arg with a space would split into 2 flags. The adapter rejects such an arg at plan time. Test: `arg_with_space_fails` in Task 1.

---

## Facts checked for this plan (2026-11-23)

| Fact | Source |
|---|---|
| `runpod_template.args` is a `string` ("Arguments passed to the container entrypoint"). `env` is `map(string)`, `ports` is `list(string)`, `disk` is a number (GB), `serverless` is a bool. `docker_entrypoint` is a list. | `terraform providers schema -json`, `runpod/runpod` 2.0.0 |
| `runpod_serverless_endpoint`: `name`, `endpoint_type`, `scaling_type`, `scaling_value` are required. `template_id`, `gpu_pools`, `excluded_types`, `gpu_count`, `workers_min`, `workers_max`, `idle_timeout` (1 to 3600), `flashboot` (`OFF`, `FLASHBOOT`, `PRIORITY_FLASHBOOT`) are optional. `request_urls.base` is computed. Env of the template is merged into the endpoint. | Same |
| The provider has no secret resource. It has `runpod_global_volume` (a volume on every worker at `/runpod-volume`), not used in this phase. | Same |
| `google/gemma-4-12B-it-qat-w4a16-ct` is not gated (`"gated": false`). Its head commit is `1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee`. So LLM-A on Runpod needs no `HF_TOKEN`. | `https://huggingface.co/api/models/google/gemma-4-12B-it-qat-w4a16-ct` |
| The same image and the same `args` already run on Vertex AI, which also passes `args` to the image ENTRYPOINT. So the open point "ENTRYPOINT accepts the args" is closed without `docker_entrypoint`. | `infra/modules/platform-vertex/main.tf`, LLM-A on Vertex AI |
| `model-service` grants `secretAccessor` for each `secret_env` entry. `cors-proxy` passes `secret_env` to it. `cors_proxy.py` already maps `auth = "runpod"` to `RUNPOD_API_KEY`. | Phase 1 code |

## Decisions in this plan (check them)

1. `HF_TOKEN` on Runpod is opt-in: `platform_options.runpod.hf_token_secret = "<Runpod secret name>"` adds `HF_TOKEN = "{{ RUNPOD_SECRET_<name> }}"`. LLM-A does not set it (repo not gated). The spec open point "`RUNPOD_SECRET_` works on Serverless templates" moves to the first gated model (phase 6). The user creates no Runpod secret in phase 3.
2. Phase 3 supports GPU and stock images on Runpod only. `spec.gpu = null` or `spec.image.own` fails at plan time with a message that names phase 6.
3. `hcp-sync.py` writes `RUNPOD_API_KEY` to every workspace (env, sensitive), and `runpod_api_key` (terraform, sensitive) to `custom-models-bootstrap`. Phase 4 adds the Baseten key in the same way.
4. The template and the endpoint both use the name `try(options.name, var.name)`, for LLM-A `llm-a-gemma4-12b`.
5. The proxy match: `auth == "runpod"`, status 400 to 599, and `b"no workers"` in the lower-case body. It answers 429 with `Retry-After: 30` and the original body.

---

## File Structure

| File | Change |
|---|---|
| `infra/modules/platform-runpod/{main,variables,outputs,versions}.tf`, `tests/platform_runpod.tftest.hcl` | New adapter |
| `infra/modules/model/{main,variables,versions}.tf`, `tests/model.tftest.hcl` | Call the adapter, allow `runpod`, proxy `secret_env` |
| `infra/modules/cors-proxy/cors_proxy.py`, `tests/test_cors_proxy.py` | `cold_answer` and the 429 mapping |
| `infra/core/provider_keys.tf` (new), `infra/core/variables.tf`, `infra/core/tests/core.tftest.hcl`, `.envrc`, `.env.example`, `scripts/hcp-sync.py`, `scripts/tests/test_hcp_sync.py` (new) | Runpod key |
| `deployments/llm-a-gemma4-12b-vllm/main.tf`, `.terraform.lock.hcl`, `tests/*.tftest.hcl`, `README.md` | LLM-A on `["vertex", "runpod"]` |
| `infra/README.md`, `docs/backends.md`, `docs/scripts.md`, `CLAUDE.md`, `.claude/skills/verify-gcp/SKILL.md` | Docs |

---

### Task 1: Adapter `platform-runpod`

**Files:**
- Create: `infra/modules/platform-runpod/main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`
- Test: `infra/modules/platform-runpod/tests/platform_runpod.tftest.hcl`

**Interfaces:**
- Consumes: the adapter input contract of `platform-vertex`: `project_id`, `region`, `name` (string), `spec` (`any`, the facade owns its type), `options` (`any`, default `{}`). `project_id` and `region` are unused here, but keep them so every adapter has the same inputs.
- Produces: output `target` = `{ id, label, url, append_path, auth, cold_start, deadline, post_apply }` (values in Global Constraints). Output `endpoint_id` = `runpod_serverless_endpoint.this.id`. Resources `runpod_template.this` and `runpod_serverless_endpoint.this`.

- [ ] **Step 1: Write the failing test**

`versions.tf`: `required_version = ">= 1.11"`, provider `runpod = { source = "runpod/runpod", version = "~> 2.0" }`. Then the test file:

```hcl
mock_provider "runpod" {
  mock_resource "runpod_serverless_endpoint" {
    defaults = { request_urls = { base = "https://ep1.api.runpod.ai" } }
  }
}

variables {
  project_id = "p"
  region     = "us-central1"
  name       = "llm-a-gemma4-12b"
  spec = {
    image        = { stock = "vllm/vllm-openai:v0.33.0" }
    args         = ["--model={model}", "--served-model-name=gemma-4-12b", "--port=8080"]
    env          = {}
    port         = 8080
    health_route = "/health"
    routes       = ["/v1/chat/completions"]
    gpu          = "L4"
    max_replicas = 1
    idle_seconds = 300
    weights      = { hf_repo = "google/gemma-4-12B-it-qat-w4a16-ct", revision = "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee", gcs_dir = "x" }
  }
  options = { extra_args = ["--enforce-eager"] }
}
```

Runs (all `command = apply`):

- `template`: `runpod_template.this.args == "--model=google/gemma-4-12B-it-qat-w4a16-ct --served-model-name=gemma-4-12b --port=8080 --enforce-eager --revision=1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"`; `image == "vllm/vllm-openai:v0.33.0"`; `serverless == true`; `ports == tolist(["8080/http"])`; `disk == 60`; `env == tomap({ HF_HUB_OFFLINE = "0", PORT = "8080", PORT_HEALTH = "8080", HEALTH_CHECK_PATH = "/health" })`; `name == "llm-a-gemma4-12b"`.
- `endpoint`: `endpoint_type == "LOAD_BALANCER"`, `scaling_type == "REQUEST_COUNT"`, `scaling_value == 4`, `gpu_pools == tolist(["AMPERE_24"])`, `gpu_count == 1`, `workers_min == 0`, `workers_max == 1`, `idle_timeout == 300`, `flashboot == "FLASHBOOT"`, `template_id == runpod_template.this.id`.
- `target`: `output.target == { id = "runpod", label = "Runpod", url = "https://ep1.api.runpod.ai", append_path = true, auth = "runpod", cold_start = "retry-429", deadline = 300, post_apply = null }`.
- `options_override` (variables `options = { gpu_pools = ["ADA_24"], excluded_types = ["NVIDIA L40"], scaling_value = 2, disk_gb = 80, env = { A = "1" }, hf_token_secret = "hf_token", name = "other" }`): the pools, excluded types, scaling value, disk and names follow; `env.A == "1"`; `env.HF_TOKEN == "{{ RUNPOD_SECRET_hf_token }}"`.
- `other_port` (spec with `port = 9000`, `health_route = "/ping"`): `ports == tolist(["9000/http"])`, `env.PORT == "9000"`, `env.PORT_HEALTH == "9000"`, `env.HEALTH_CHECK_PATH == "/ping"`.
- `revision_required` (spec `weights` without `revision`): `expect_failures = [runpod_template.this]`.
- `arg_with_space_fails` (spec `args = ["--chat-template=a b"]`): `expect_failures = [runpod_template.this]`.
- `cpu_fails` (spec `gpu = null`) and `own_image_fails` (spec `image = { own = "x:1" }`): `expect_failures = [runpod_template.this]`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd infra/modules/platform-runpod && terraform init -backend=false && terraform test`
Expected: FAIL (no `runpod_template.this` in the module).

- [ ] **Step 3: Implement the adapter in `main.tf` and `outputs.tf`**

- `local.args = [for a in concat(spec.args, try(options.extra_args, []), revision flag) : replace(a, "{model}", spec.weights.hf_repo)]`, then `args = join(" ", local.args)` on the template. The revision flag is `["--revision=${spec.weights.revision}"]` when `spec.weights` is set.
- `env = merge(try(spec.env, {}), { HF_HUB_OFFLINE = "0", PORT, PORT_HEALTH, HEALTH_CHECK_PATH }, hf_token_secret != null ? { HF_TOKEN = "{{ RUNPOD_SECRET_${hf_token_secret} }}" } : {}, try(options.env, {}))`. Port values are strings (`tostring`).
- The 4 failure cases are `lifecycle.precondition` blocks on `runpod_template.this`, each with a message: "spec.weights.revision (a commit sha) is required on Runpod", "Runpod args are 1 string: an arg must not contain a space (<arg>)", "Runpod in phase 3: GPU models only (spec.gpu)", "Runpod in phase 3: stock images only. Own images come in phase 6".
- `excluded_types = try(options.excluded_types, [])`. Set `cpu` never.
- A file header comment in the style of `platform-vertex/main.tf`: what the adapter maps, and that `post_apply` is null because the endpoint is ready after apply.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd infra/modules/platform-runpod && terraform test && terraform fmt -check -recursive && tflint`
Expected: all runs pass; fmt and tflint print nothing.

- [ ] **Step 5: Commit**

```bash
git add infra/modules/platform-runpod
git commit -m "feat(infra): platform-runpod adapter (template + load balancing endpoint, scale to 0)"
```

---

### Task 2: The facade calls the Runpod adapter

**Files:**
- Modify: `infra/modules/model/main.tf`, `variables.tf` (platform validation), `versions.tf` (add `runpod`)
- Test: `infra/modules/model/tests/model.tftest.hcl`

**Interfaces:**
- Consumes: `module.runpod[0].target` (Task 1). Module `cors-proxy` input `secret_env` (map env name -> secret ID, phase 1).
- Produces: `targets.runpod` in the facade output, gateway paths `/runpod<route>`, `ui_platforms` entry `{ id = "runpod", label = "Runpod", base_url = "<gateway>/runpod", cold_start = "retry-429" }`. Secret ID convention: `<auth>-api-key` (`runpod-api-key`), env name `upper(<auth>)_API_KEY`.

- [ ] **Step 1: Write the failing tests**

Add `mock_provider "runpod"` with the same `request_urls` default as Task 1. Add `revision = "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"` to the shared `weights`. Keep every phase 1 and 2 run unchanged (they use `platforms = ["vertex"]`). New runs:

- `vertex_and_runpod` (`platforms = ["vertex", "runpod"]`, `platform_options.runpod = { gpu_pools = ["AMPERE_24"] }`): `keys(output.targets) == ["runpod", "vertex"]`; `output.platforms == tolist(["vertex", "runpod"])`; `keys(output.openapi.paths) == ["/runpod/v1/chat/completions", "/v1/chat/completions", "/vertex/v1/chat/completions"]`; `jsondecode(module.cors_proxy.env.TARGETS).runpod == { url = "https://ep1.api.runpod.ai", append_path = true, auth = "runpod" }`; `module.cors_proxy.env.DEFAULT == "vertex"`; `[for p in output.ui_platforms : p.id] == ["vertex", "runpod"]`; `output.ui_platforms[1].cold_start == "retry-429"`.
- `proxy_gets_runpod_key` (same variables): `module.cors_proxy.secret_env == { RUNPOD_API_KEY = "runpod-api-key" }`. `cors-proxy` has no such output yet: add `output "secret_env"` (value `var.secret_env`, for tests) next to its `env` output.
- `vertex_only_has_no_secret` (`platforms = ["vertex"]`): the proxy `secret_env` is empty.
- `runpod_only` (`platforms = ["runpod"]`): `output.vertex == null`; `length(module.cors_proxy.google_project_iam_member.predict) == 0`; `module.cors_proxy.env.DEFAULT == "runpod"`; `keys(output.openapi.paths) == ["/runpod/v1/chat/completions", "/v1/chat/completions"]`.
- `unknown_platform_fails` (`platforms = ["vertex", "modal"]`): `expect_failures = [var.platforms]`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra/modules/model && terraform init -backend=false && terraform test`
Expected: FAIL. `vertex_and_runpod` fails on the `platforms` validation ("Supported platform ids: vertex.").

- [ ] **Step 3: Implement**

- `variables.tf`: allowed ids `["vertex", "runpod"]`. Message: "Supported platform ids: vertex, runpod." Remove the phase 1 comment about later phases for Runpod; keep the Baseten note.
- `main.tf`: `module "runpod"` with `count = contains(var.platforms, "runpod") ? 1 : 0`, the same inputs as `module "vertex"`, `options = try(var.platform_options.runpod, {})`. Add the entry to `local.all_targets`. Proxy input `secret_env = { for a in distinct([for t in values(local.targets) : t.auth if t.auth != "google"]) : "${upper(a)}_API_KEY" => "${a}-api-key" }`.
- `versions.tf`: add `runpod = { source = "runpod/runpod", version = "~> 2.0" }`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/modules/model && terraform test` and `cd infra/modules/cors-proxy && terraform init -backend=false && terraform test`
Expected: all runs pass in both modules.

- [ ] **Step 5: Commit**

```bash
git add infra/modules/model infra/modules/cors-proxy
git commit -m "feat(infra): model facade calls platform-runpod; the proxy gets the Runpod key secret"
```

---

### Task 3: The proxy maps "no workers available" to 429

**Files:**
- Modify: `infra/modules/cors-proxy/cors_proxy.py` (`forward`, new `cold_answer`)
- Test: `infra/modules/cors-proxy/tests/test_cors_proxy.py`

**Interfaces:**
- Produces: `cold_answer(auth: str, status: int, body: bytes) -> bool`. True means "answer 429 with `Retry-After: 30`".

- [ ] **Step 1: Write the failing tests**

```python
class ColdAnswer(unittest.TestCase):
    def test_runpod_no_workers_is_cold(self):
        self.assertTrue(cp.cold_answer("runpod", 503, b'{"error":"No workers available"}'))

    def test_runpod_no_workers_on_400_is_cold(self):
        self.assertTrue(cp.cold_answer("runpod", 400, b"no workers available"))

    def test_runpod_other_error_is_not_cold(self):
        self.assertFalse(cp.cold_answer("runpod", 500, b'{"error":"CUDA out of memory"}'))

    def test_good_answer_is_never_cold(self):
        self.assertFalse(cp.cold_answer("runpod", 200, b"no workers"))

    def test_vertex_is_not_mapped(self):
        self.assertFalse(cp.cold_answer("google", 503, b"no workers available"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra/modules/cors-proxy && python3 -m unittest tests.test_cors_proxy -v`
Expected: FAIL with `AttributeError: module 'cors_proxy' has no attribute 'cold_answer'`.

- [ ] **Step 3: Implement**

`cold_answer` with the rule of decision 5. In `forward`: when `t["auth"] != "google"` and `r.status >= 400`, read the body (`r.read()`), and reply 429 with `{"Content-Type": <upstream type>, "Retry-After": "30"}` and the body when `cold_answer` is True, else reply the upstream status with that body. When it maps, it also prints 1 line to stderr (Cloud Run logs): `runpod cold: <status> <first 200 bytes of the body>`, so the user can read the raw answer. It prints no header and no key. All other answers keep the streaming path (`iter(r.read1 ...)`) as today. One comment line on `cold_answer`: the real status and body come from the first cold call (Open points of the spec), and a change goes only here.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/modules/cors-proxy && python3 -m unittest discover -s tests -v`
Expected: all tests pass (the phase 1 tests too).

- [ ] **Step 5: Commit**

```bash
git add infra/modules/cors-proxy
git commit -m "feat(cors-proxy): Runpod 'no workers available' becomes 429 with Retry-After"
```

---

### Task 4: The Runpod key in `.env`, HCP and Secret Manager

**Files:**
- Create: `infra/core/provider_keys.tf`, `scripts/tests/test_hcp_sync.py`
- Modify: `infra/core/variables.tf`, `infra/core/tests/core.tftest.hcl` (and every other `infra/core/tests/*.tftest.hcl` that sets `hf_token` in `variables`), `.envrc`, `.env.example`, `scripts/hcp-sync.py`

**Interfaces:**
- Produces: Secret Manager secret `runpod-api-key` (read by the proxy through Task 2). Terraform variable `runpod_api_key` in `infra/core` (ephemeral, sensitive, like `hf_token`). Env var `RUNPOD_API_KEY` in every HCP workspace (the Runpod provider reads it). In `hcp-sync.py`: dict `PROVIDER_KEYS = {"RUNPOD_API_KEY": E("RUNPOD_API_KEY")}`, upserted as category `env` in every workspace; `"RUNPOD_API_KEY"` and `"runpod_api_key"` in `SENSITIVE`.

- [ ] **Step 1: Write the failing tests**

`infra/core/tests/core.tftest.hcl`: add `runpod_api_key = "test"` to `variables` (in every core test file). New run `runpod_key_secret` (`command = plan`): `google_secret_manager_secret.runpod_api_key.secret_id == "runpod-api-key"`; `google_secret_manager_secret_version.runpod_api_key.secret_data_wo_version == 1`.

`scripts/tests/test_hcp_sync.py` (load `hcp-sync.py` with `importlib`, as `test_deploy.py` does, inside `unittest.mock.patch.dict(os.environ, {"TF_CLOUD_ORGANIZATION": "o", "TF_CLOUD_PROJECT": "p", "TF_TOKEN_app_terraform_io": "t", "RUNPOD_API_KEY": "k"})`):

- `test_runpod_key_goes_to_every_workspace_as_env`: `sync.PROVIDER_KEYS == {"RUNPOD_API_KEY": "k"}`.
- `test_keys_are_sensitive`: `{"RUNPOD_API_KEY", "runpod_api_key"} <= sync.SENSITIVE`.
- `test_core_gets_the_terraform_variable`: `sync.WORKSPACES["custom-models-bootstrap"][1]["runpod_api_key"] == "k"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra/core && terraform init -backend=false && terraform test` and `cd scripts && python3 -m unittest tests.test_hcp_sync -v`
Expected: core fails ("Reference to undeclared resource" or "undeclared input variable runpod_api_key"); the Python tests fail with `AttributeError: ... PROVIDER_KEYS`.

- [ ] **Step 3: Implement**

- `infra/core/variables.tf`: `variable "runpod_api_key"`, `ephemeral = true`, `sensitive = true`, description "Runpod API key. Ephemeral: it goes to Secret Manager (runpod-api-key) and never into state. The CORS proxy of each model reads it."
- `infra/core/provider_keys.tf`: secret `runpod-api-key` and its version, the same pattern as `hf-token` in `weights_copy.tf` (auto replication, `depends_on` the APIs, `secret_data_wo`, `secret_data_wo_version = 1`, the rotate comment).
- `.envrc`: `export TF_VAR_runpod_api_key="${RUNPOD_API_KEY:-}"` with a comment. `.env.example`: a `# Runpod` block with `RUNPOD_API_KEY=` and 1 comment line (where the key comes from: Runpod console, Settings, API Keys; infra/core writes it to `runpod-api-key`; hcp-sync gives it to every workspace).
- `scripts/hcp-sync.py`: `runpod_api_key` in the core variables, `PROVIDER_KEYS`, `SENSITIVE`, and in `main()` 1 loop that upserts each non-empty `PROVIDER_KEYS` entry as `env`. Update the docstring.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/core && terraform test` and `cd scripts && python3 -m unittest discover -s tests -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add infra/core .envrc .env.example scripts/hcp-sync.py scripts/tests/test_hcp_sync.py
git commit -m "feat(core): Runpod API key in Secret Manager and in every HCP workspace"
```

---

### Task 5: LLM-A on `["vertex", "runpod"]`

**Files:**
- Modify: `deployments/llm-a-gemma4-12b-vllm/main.tf`, `.terraform.lock.hcl`, `tests/gateway.tftest.hcl`, `tests/alerts.tftest.hcl`, `README.md`

**Interfaces:**
- Consumes: the facade with `runpod` (Task 2). `ui_platforms` (phase 2).

- [ ] **Step 1: Write the failing tests**

In both test files: add `mock_provider "runpod"` with the `request_urls` default of Task 1. In `gateway.tftest.hcl`:

- `gateway_requires_api_key`: the path list becomes `["/runpod/v1/chat/completions", "/v1/chat/completions", "/vertex/v1/chat/completions"]` (message: "the old path, the vertex path and the runpod path").
- `outputs_for_scripts`: `output.platforms == tolist(["vertex", "runpod"])` (message: "LLM-A runs on vertex (default) and runpod"); `length(output.ui.platforms) == 2 && output.ui.platforms[1].id == "runpod"`; `output.ui.base_url` stays `"${output.gateway_url}/vertex"`.
- New run `runpod_flags`: `module.model.module.runpod[0].runpod_template.this.args` does not contain `--kv-cache-dtype` and does not contain `runai_streamer`, and contains `--revision=1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd deployments/llm-a-gemma4-12b-vllm && terraform init -backend=false && terraform test`
Expected: FAIL on the path list and on `output.platforms`.

- [ ] **Step 3: Implement**

`main.tf`: `platforms = ["vertex", "runpod"]` (comment: the first one is the default). `weights` gets `revision = "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"` (comment: the Hugging Face commit; Runpod downloads exactly this one). `platform_options.runpod = { gpu_pools = ["AMPERE_24"] }` with the comment "L4, A5000 or 3090: Ampere has no native FP8, so no --kv-cache-dtype=fp8 here". `terraform init -backend=false` adds `runpod/runpod` to `.terraform.lock.hcl`; keep that change.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd deployments/llm-a-gemma4-12b-vllm && terraform test` and then `./scripts/check.py` from the repo root
Expected: all runs pass; check.py prints all roots ok.

- [ ] **Step 5: Write the README section**

New section "Runpod (2026-11-23)" in the LLM-A README, before "Test":

1. One-time setup: link to the infra/README section of Task 6.
2. Expected `terraform plan`: create `runpod_template` and `runpod_serverless_endpoint`, create the `secretAccessor` member of the proxy SA on `runpod-api-key`, update the proxy service in place (new `TARGETS`, new secret env var), a new API config with the `/runpod/` path, the gateway updated in place. No Vertex AI endpoint and no gateway is replaced.
3. After apply: `./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm`, then `./scripts/deploy.py status deployments/llm-a-gemma4-12b-vllm` (expect `runpod: deployed`), then a full `./scripts/ui-deploy.py`.
4. Test call: the curl of the "Test" section with `/runpod/v1/chat/completions`. Warning first: a call starts a Runpod GPU worker, billed per second until `idle_timeout` (300 s) ends.
5. A table to fill at the first cold call: the HTTP status and body at 0 workers (the `runpod cold:` line in the proxy log), the time to the first answer, and the GPU type that Runpod gave.

Update the "Test UI and platforms" section: the tab now shows the picker with Vertex AI and Runpod.

- [ ] **Step 6: Commit**

```bash
git add deployments/llm-a-gemma4-12b-vllm
git commit -m "feat(llm-a): run on vertex and runpod"
```

---

### Task 6: Docs

**Files:**
- Modify: `infra/README.md`, `docs/backends.md`, `docs/scripts.md`, `CLAUDE.md`, `.claude/skills/verify-gcp/SKILL.md`

- [ ] **Step 1: Write the docs**

- `infra/README.md`:
  - New section "Module: platform-runpod" after "Module: platform-vertex". Give the inputs, the options (`name`, `gpu_pools`, `excluded_types`, `scaling_value`, `disk_gb`, `extra_args`, `env`, `hf_token_secret`), the target values, and the phase 3 limits (GPU and stock images only).
  - New section "Runpod setup (once)": make an account, add credit, make an API key (console, Settings, API Keys), put it in `.env` as `RUNPOD_API_KEY`, run `./scripts/hcp-sync.py`, apply `infra/core`. Gated Hugging Face repos: make a Runpod secret and set `hf_token_secret` (not verified on Serverless). Limits: 5 workers by default, $80 per hour spend limit.
  - In "Module: model (platforms)": `runpod` is a supported id, and the facade sets the proxy `secret_env`.
  - In "CORS proxy": the 429 mapping of `cold_answer`.
- `docs/backends.md`: Runpod as a backend of the proxy, 1 line in the diagram only if the diagram lists the platforms (use the `diagrams` skill and its render check when a diagram changes).
- `docs/scripts.md`: `hcp-sync.py` also writes `RUNPOD_API_KEY`.
- `CLAUDE.md`: the `infra/modules/model/` bullet lists `platform-runpod`; the secrets table gets `RUNPOD_API_KEY`.
- `.claude/skills/verify-gcp/SKILL.md`: the paid level calls each platform path of a model (`/<platform><route>`), and says that a Runpod call bills a worker.

- [ ] **Step 2: Verify**

Run: `./scripts/check.py` and `terraform fmt -recursive -check`
Expected: all ok, fmt prints nothing.

- [ ] **Step 3: Commit**

```bash
git add infra/README.md docs CLAUDE.md .claude/skills/verify-gcp/SKILL.md
git commit -m "docs: Runpod platform (multi-platform phase 3)"
```

---

## What the user runs after this phase

Do these steps after the phase 1 and phase 2 applies of LLM-A.

1. Make the Runpod account and the API key. Put the key in `.env` as `RUNPOD_API_KEY`.
2. Run `./scripts/hcp-sync.py --dry-run`, then `./scripts/hcp-sync.py`.
3. Apply `infra/core`. The plan must show only the new secret `runpod-api-key` and its version.
4. Run `terraform plan` in `deployments/llm-a-gemma4-12b-vllm`. Compare it with the README section "Runpod (2026-11-23)". Then apply.
5. Run `./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm`, `./scripts/deploy.py status deployments/llm-a-gemma4-12b-vllm` and a full `./scripts/ui-deploy.py`.
6. Record the cold answer: make the first call to `/runpod/v1/chat/completions`. Write the raw status and body at 0 workers, the cold start time and the GPU type into the README table. If the raw answer does not match `cold_answer`, send it to the agent: only that function changes.
