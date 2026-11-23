# Multi-platform phase 4 (Baseten) Implementation Plan

> Update 2026-11-23: Baseten is deferred. The Baseten account answered "Your account does not support deploying custom models. Contact support@baseten.co to enable." on 2 apply attempts, so the user decided to remove Baseten for now. The code (adapter `platform-baseten`, facade wiring, keys, `scale-watch` reader) is not on master. The git tag `archive/baseten-platform` keeps the last Baseten version; restore it from there after Baseten support enables custom models. Runpod is the live second platform.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM-A runs on Vertex AI, Runpod and Baseten at the same time. A call to `<gateway>/baseten/v1/chat/completions` goes through the same gateway, API key and CORS proxy to a Baseten model that scales to 0.

**Architecture:** A new adapter `infra/modules/platform-baseten` turns the model spec into 1 `baseten_model` in managed mode (inline `push.config` with the stock vLLM image as a custom Docker server, weights from Hugging Face through Baseten BDN) and gives the common `target` output. The `model` facade calls it with `count`. The proxy needs no code change: it already sends `Authorization: Bearer <BASETEN_API_KEY>`, and Baseten holds the request at 0 replicas, so there is no 429 to map. `infra/core` stores the Baseten key in Secret Manager (write-only) and the Hugging Face token as a Baseten secret.

**Tech Stack:** Terraform >= 1.11 (`terraform test` with `mock_provider`), provider `basetenlabs/baseten ~> 0.1.0` (0.1.0 checked on 2026-11-23 with `terraform providers schema -json`), Python 3 standard library (`unittest`).

**Spec:** `docs/specs/2026-11-22-multi-platform-design.md` (sections "Adapter interface", "What each adapter does", "Secrets and keys", "Phases" row 4, "Open points", "Risks"). Phase 3 plan: `docs/specs/2026-11-23-multi-platform-phase3-plan.md` (the Runpod adapter is the pattern for this phase).

## Global Constraints

- One adapter per platform. No copied gateway, proxy or deploy code for Baseten. No code outside the adapter checks the platform id, except the proxy (credential) and `deploy.py` (post-apply step).
- `min_replica = 0` on the `production` environment. `max_replica = spec.max_replicas` (1 for LLM-A).
- The Baseten API key never goes into git, `models.json`, the browser or a Terraform state. `infra/core` writes it with `secret_data_wo`. The Hugging Face token goes to Baseten with `value_wo`. HCP workspaces get `BASETEN_API_KEY` as a sensitive env var.
- Baseten target: `id = "baseten"`, `label = "Baseten"`, `url = "https://model-<baseten_model.this.id>.api.baseten.co/environments/production/sync"`, `append_path = true`, `auth = "baseten"`, `cold_start = "hold"`, `deadline = 600`, `post_apply = null`.
- `{model}` on Baseten = `/models/weights` (the BDN mount). Weights source = `hf://<hf_repo>@<revision>`. `HF_HUB_OFFLINE = "1"`.
- Port rule (spec): when `spec.port` is 8080, the adapter uses 8000. It changes the arg `--port=8080` to `--port=8000`, sets `server_port = 8000` and `PORT = "8000"`. Any other port stays.
- Defaults: `concurrency_target = 4`, `predict_concurrency` = the same value, `scale_down_delay = spec.idle_seconds`, `deploy_timeout_minutes = 30`, resource `timeouts` 60 min, `deletion_protection = false`, `environment_deletion_protection = false`.
- Scripts: Python 3 standard library only. Each script loads `.env` itself. No `direnv exec` in front of a script.
- The agent does not run apply, deploy or test calls on real GCP or Baseten, unless the user asks in the same message. It verifies with `./scripts/check.py` and `terraform fmt -recursive -check`.
- Docs prose in Simplified Technical English.

## Review Focus

1. Port 8080: the server must listen on 8000 on Baseten and nowhere else. A model on port 9000 keeps 9000. Test: `port_8080_moves_to_8000` and `other_port` in Task 1.
2. `start_command` is 1 string: an arg with a space or a quote breaks it. The adapter rejects such an arg at plan time, as on Runpod. Test: `arg_with_space_fails` in Task 1.
3. A stock image without `platform_options.baseten.entrypoint`: Baseten replaces the image ENTRYPOINT with `start_command`, so the server would start without `vllm serve`. The plan must fail with a clear message. Test: `entrypoint_required` in Task 1.
4. A model on Baseten only: the proxy default is `baseten`, the proxy gets only `BASETEN_API_KEY`, and the proxy timeout is 600 s. Test: `baseten_only` in Task 2.
5. 3 platforms: the gateway gives 600 s only to the `/baseten/` path. The old path keeps the deadline of the default platform (300 s). The proxy gets both provider keys. Test: `three_platforms` in Task 2.

---

## Facts checked for this plan (2026-11-23)

| Fact | Source |
|---|---|
| `baseten_model`: `name`, `deletion_protection` (default true), `environment_deletion_protection` (default true), `environments` (map: `autoscaling` with `min_replica`, `max_replica`, `scale_down_delay`, `concurrency_target`; `promotion`), `push` (`config` dynamic, `environment`, `wait`, `deploy_timeout_minutes` 10 to 1440, `triggers`), `timeouts` (`create`, `update`). Computed `id`, `deployment_id`. No URL attribute. | `terraform providers schema -json`, `basetenlabs/baseten` 0.1.0 |
| `baseten_secret`: `name`, `value_wo` (write-only, sensitive), `value_wo_version`, `deletion_protection`. | Same |
| The provider reads `BASETEN_API_KEY` from the env. | Same (provider block) |
| Editing `push.config` pushes a new deployment. A push never removes the old deployment. The apply that creates the model writes the environment settings after the first push, so the first deployment starts on the Baseten defaults. | Provider docs `docs/resources/model.md` |
| `docker_server.start_command` is required (unless `no_build`, which needs Baseten support). It replaces the image ENTRYPOINT. `server_port` is required, and 8080 is reserved. `predict_endpoint`, `readiness_endpoint`, `liveness_endpoint`. | docs.baseten.co `reference/truss-configuration` |
| `weights` is a list of `{ source = "hf://<repo>@<revision>", mount_location, auth_secret_name }`. `auth_secret_name` is needed only for private or gated repos. `secrets` is a list of names (open point "secrets form" closed: this adapter needs only `auth_secret_name`). | Same |
| `resources.accelerator = "L4"` gives the smallest instance with 1 L4. `instance_type` (for example `L4:4x16`) selects an exact SKU. | Same |
| `runtime.predict_concurrency` defaults to 1. `runtime.health_checks.startup_threshold_seconds` defaults to 1800 s. | Same |
| The call URL is `https://model-<id>.api.baseten.co/environments/production/sync/<route>`, with `Authorization: Bearer <key>` (open point "auth header" closed: the proxy already sends `Bearer`). | docs.baseten.co `examples/deploy-a-hugging-face-model` |
| The ENTRYPOINT of `vllm/vllm-openai:v0.33.0` (linux/amd64) is `["vllm", "serve"]`. Vertex AI and Runpod pass `args` to it. So the Baseten `start_command` is `vllm serve <args>`. | Docker Hub registry API, image config |
| API Gateway: the maximum `x-google-backend` deadline is 600 s (open point "1200 s deadline" closed: not accepted). | cloud.google.com `api-gateway/docs/oasv2-extensions` |

## Decisions in this plan (check them)

1. Gateway deadline for Baseten is 600 s, not the 1200 s of the spec, because API Gateway accepts at most 600 s. Baseten holds a request for up to 1200 s. So a cold start above 600 s gives a gateway timeout (504) to the UI. The replica keeps starting, and the next call works. The README cold-start table records the real time.
2. `platform_options.baseten.entrypoint` is required for stock images (`"vllm serve"` for LLM-A). The adapter does not guess the image ENTRYPOINT.
3. `HF_TOKEN` on Baseten is opt-in, as on Runpod: `platform_options.baseten.hf_token_secret = "hf_access_token"` adds `auth_secret_name` to the weights entry. LLM-A does not set it (the repo is not gated). `infra/core` still creates the Baseten secret `hf_access_token` (spec), so a gated model needs only the option.
4. `push.wait = true` and `environment = "production"`. The apply waits until the deployment is active. This starts 1 GPU replica during the apply, which bills until `scale_down_delay` (300 s) ends. The README says so before the apply step.
5. `promotion.promotion_cleanup_strategy = "DEACTIVATE"`: a new push deactivates the old deployment, so old deployments do not stay ready.
6. `hcp-sync.py` writes `BASETEN_API_KEY` to every workspace (env, sensitive) and `baseten_api_key` (terraform, sensitive) to `custom-models-bootstrap`, the same way as the Runpod key.
7. Phase 4 supports GPU and stock images on Baseten only. `spec.gpu = null` or `spec.image.own` fails at plan time with a message that names phase 6.

---

## File Structure

| File | Change |
|---|---|
| `infra/modules/platform-baseten/{main,variables,outputs,versions}.tf`, `tests/platform_baseten.tftest.hcl` | New adapter |
| `infra/modules/model/{main,variables,versions,outputs}.tf`, `tests/model.tftest.hcl` | Call the adapter, allow `baseten` |
| `infra/core/provider_keys.tf`, `infra/core/versions.tf`, `infra/core/variables.tf`, `infra/core/tests/*.tftest.hcl`, `infra/core/.terraform.lock.hcl`, `.envrc`, `.env.example`, `scripts/hcp-sync.py`, `scripts/tests/test_hcp_sync.py` | Baseten key and Hugging Face secret |
| `deployments/llm-a-gemma4-12b-vllm/main.tf`, `.terraform.lock.hcl`, `tests/*.tftest.hcl`, `README.md` | LLM-A on `["vertex", "runpod", "baseten"]` |
| `infra/README.md`, `docs/backends.md`, `docs/scripts.md`, `docs/auth-and-ui.md`, `CLAUDE.md`, `.claude/skills/verify-gcp/SKILL.md` | Docs |

---

### Task 1: Adapter `platform-baseten`

**Files:**
- Create: `infra/modules/platform-baseten/main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`
- Test: `infra/modules/platform-baseten/tests/platform_baseten.tftest.hcl`

**Interfaces:**
- Consumes: the adapter input contract (as `platform-runpod`): `project_id`, `region` (both unused, with `# tflint-ignore: terraform_unused_declarations`), `name`, `spec` (`any`), `options` (`any`, default `{}`). Options: `name`, `entrypoint`, `extra_args`, `env`, `concurrency_target`, `instance_type`, `hf_token_secret`, `deploy_timeout_minutes`.
- Produces: output `target` (values in Global Constraints). Output `model_id` = `baseten_model.this.id`. Output `config` = the inline push config (for tests). Resource `baseten_model.this`.

- [ ] **Step 1: Write the failing test**

`versions.tf`: `required_version = ">= 1.11"`, provider `baseten = { source = "basetenlabs/baseten", version = "~> 0.1.0" }`. Test file: `mock_provider "baseten"` with `mock_resource "baseten_model" { defaults = { id = "abc123" } }`. Variables: the LLM-A spec of the phase 3 Task 1 test (`args = ["--model={model}", "--served-model-name=gemma-4-12b", "--port=8080"]`, port 8080, `/health`, 1 route, L4, 1 replica, 300 s, weights with revision `1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee`), and `options = { entrypoint = "vllm serve", extra_args = ["--kv-cache-dtype=fp8"] }`.

Runs (all `command = apply`):

- `port_8080_moves_to_8000`: `output.config.docker_server == { start_command = "vllm serve --model=/models/weights --served-model-name=gemma-4-12b --port=8000 --kv-cache-dtype=fp8", server_port = 8000, predict_endpoint = "/v1/chat/completions", readiness_endpoint = "/health", liveness_endpoint = "/health" }`; `output.config.environment_variables == { HF_HUB_OFFLINE = "1", PORT = "8000" }`.
- `config`: `output.config.base_image == { image = "vllm/vllm-openai:v0.33.0" }`; `output.config.weights == [{ source = "hf://google/gemma-4-12B-it-qat-w4a16-ct@1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee", mount_location = "/models/weights" }]`; `output.config.resources == { accelerator = "L4", use_gpu = true }`; `output.config.runtime.predict_concurrency == 4`.
- `model`: `baseten_model.this.name == "llm-a-gemma4-12b"`; `deletion_protection == false`; `environment_deletion_protection == false`; `push.environment == "production"`; `push.wait == true`; `push.deploy_timeout_minutes == 30`; `environments.production.autoscaling == { min_replica = 0, max_replica = 1, scale_down_delay = 300, concurrency_target = 4 }` (compare the 4 fields one by one if the object has computed fields); `environments.production.promotion.promotion_cleanup_strategy == "DEACTIVATE"`.
- `target`: `output.target == { id = "baseten", label = "Baseten", url = "https://model-abc123.api.baseten.co/environments/production/sync", append_path = true, auth = "baseten", cold_start = "hold", deadline = 600, post_apply = null }`.
- `options_override` (`options = { entrypoint = "vllm serve", name = "other", concurrency_target = 2, instance_type = "L4:4x16", hf_token_secret = "hf_access_token", env = { A = "1" }, deploy_timeout_minutes = 45 }`): name `"other"`; `concurrency_target == 2` and `predict_concurrency == 2`; `resources == { instance_type = "L4:4x16" }`; `weights[0].auth_secret_name == "hf_access_token"`; `environment_variables.A == "1"`; `deploy_timeout_minutes == 45`.
- `other_port` (spec `port = 9000`, `args = ["--port=9000"]`, `health_route = "/ping"`): `server_port == 9000`; `start_command == "vllm serve --port=9000 --kv-cache-dtype=fp8"`; `readiness_endpoint == "/ping"`.
- `entrypoint_required` (`options = {}`), `revision_required` (weights without `revision`), `arg_with_space_fails` (`args = ["--chat-template=a b"]`), `model_without_weights_fails` (`weights = null`, args keep `{model}`), `cpu_fails` (`gpu = null`), `own_image_fails` (`image = { own = "x:1" }`): each `expect_failures = [baseten_model.this]`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd infra/modules/platform-baseten && terraform init -backend=false && terraform test`
Expected: FAIL (no `baseten_model.this` in the module).

- [ ] **Step 3: Implement the adapter**

- `local.port = spec.port == 8080 ? 8000 : spec.port` (`try(spec.port, 8080)` first). Arg map: `{model}` becomes `/models/weights`; an arg equal to `--port=8080` becomes `--port=8000` only when the port moved.
- `local.config` = `{ base_image, docker_server, environment_variables, weights, resources, runtime = { predict_concurrency } }`. `start_command = join(" ", concat([options.entrypoint], args))`. `environment_variables = merge(spec.env, { HF_HUB_OFFLINE = "1", PORT }, options.env)`. Add `auth_secret_name` to the weights entry only when `hf_token_secret` is set. `resources` is `{ instance_type }` when the option is set, else `{ accelerator = spec.gpu, use_gpu = true }`.
- `bad_args` as in `platform-runpod` (white space, a quote, or a leading `{`).
- Preconditions on `baseten_model.this`, each with a message: entrypoint required ("platform_options.baseten.entrypoint is required: Baseten replaces the image ENTRYPOINT with start_command (vllm/vllm-openai: \"vllm serve\")."), revision required, bad args, `{model}` without weights, GPU only, stock image only (phase 6).
- `timeouts = { create = "60m", update = "60m" }`.
- A header comment in the style of `platform-runpod/main.tf`: what it maps, the port rule, and that `post_apply` is null because `push.wait` waits for the deployment.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd infra/modules/platform-baseten && terraform test && terraform fmt -check -recursive && tflint`
Expected: all runs pass; fmt and tflint print nothing.

- [ ] **Step 5: Commit**

```bash
git add infra/modules/platform-baseten
git commit -m "feat(infra): platform-baseten adapter (custom vLLM server, BDN weights, scale to 0)"
```

---

### Task 2: The facade calls the Baseten adapter

**Files:**
- Modify: `infra/modules/model/main.tf`, `variables.tf` (validation), `versions.tf` (add `baseten`), `outputs.tf` (add `baseten_config`)
- Test: `infra/modules/model/tests/model.tftest.hcl`

**Interfaces:**
- Consumes: `module.baseten[0].target` and `module.baseten[0].config` (Task 1).
- Produces: `targets.baseten`, gateway paths `/baseten<route>` with deadline 600, `ui_platforms` entry `{ id = "baseten", label = "Baseten", base_url = "<gateway>/baseten", cold_start = "hold" }`, proxy `secret_env` entry `BASETEN_API_KEY = "baseten-api-key"`. Output `baseten_config` (null without baseten).

- [ ] **Step 1: Write the failing tests**

Add `mock_provider "baseten"` with the `id = "abc123"` default of Task 1. Keep every earlier run. New runs:

- `three_platforms` (`platforms = ["vertex", "runpod", "baseten"]`, `platform_options = { runpod = {}, baseten = { entrypoint = "vllm serve" } }`): `keys(output.targets) == ["baseten", "runpod", "vertex"]`; `module.cors_proxy.secret_env == tomap({ BASETEN_API_KEY = "baseten-api-key", RUNPOD_API_KEY = "runpod-api-key" })`; `module.cors_proxy.env.TIMEOUT == "600"`; `output.openapi.paths["/baseten/v1/chat/completions"].post["x-google-backend"].deadline == 600`; `output.openapi.paths["/v1/chat/completions"].post["x-google-backend"].deadline == 300`; `output.ui_platforms[2].cold_start == "hold"`.
- `baseten_only` (`platforms = ["baseten"]`): `output.vertex == null`; `module.cors_proxy.env.DEFAULT == "baseten"`; `module.cors_proxy.secret_env == tomap({ BASETEN_API_KEY = "baseten-api-key" })`; `keys(output.openapi.paths) == ["/baseten/v1/chat/completions", "/v1/chat/completions"]`.
- `unknown_platform_fails` stays (`modal`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra/modules/model && terraform init -backend=false && terraform test`
Expected: FAIL on the `platforms` validation ("Supported platform ids: vertex, runpod.").

- [ ] **Step 3: Implement**

- `variables.tf`: ids `["vertex", "runpod", "baseten"]`, message "Supported platform ids: vertex, runpod, baseten." Remove the "Phase 4 adds baseten" comment.
- `main.tf`: `module "baseten"` like `module "runpod"`, the entry in `local.all_targets`, and the header comment lists baseten. `secret_env` and `timeout` need no change.
- `versions.tf`: `baseten = { source = "basetenlabs/baseten", version = "~> 0.1.0" }`.
- `outputs.tf`: `baseten_config = try(module.baseten[0].config, null)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/modules/model && terraform test`
Expected: all runs pass.

- [ ] **Step 5: Commit**

```bash
git add infra/modules/model
git commit -m "feat(infra): model facade calls platform-baseten"
```

---

### Task 3: The Baseten key and the Hugging Face secret

**Files:**
- Modify: `infra/core/provider_keys.tf`, `infra/core/versions.tf`, `infra/core/variables.tf`, `infra/core/tests/core.tftest.hcl`, `infra/core/tests/gateways.tftest.hcl`, `infra/core/.terraform.lock.hcl`, `.envrc`, `.env.example`, `scripts/hcp-sync.py`, `scripts/tests/test_hcp_sync.py`

**Interfaces:**
- Produces: Secret Manager secret `baseten-api-key` (the proxy reads it through Task 2). Baseten secret `hf_access_token` (Task 1 option `hf_token_secret`). Terraform variable `baseten_api_key` in `infra/core` (ephemeral, sensitive). `PROVIDER_KEYS` in `hcp-sync.py` gets `"BASETEN_API_KEY": E("BASETEN_API_KEY")`.

- [ ] **Step 1: Write the failing tests**

Both core test files: `mock_provider "baseten" {}` and `baseten_api_key = "test"` in `variables`. New run `baseten_keys` in `core.tftest.hcl` (`command = plan`): `google_secret_manager_secret.baseten_api_key.secret_id == "baseten-api-key"`; `google_secret_manager_secret_version.baseten_api_key.secret_data_wo_version == "1"`; `baseten_secret.hf_access_token.name == "hf_access_token"`; `baseten_secret.hf_access_token.value_wo_version == 1`.

`scripts/tests/test_hcp_sync.py`: add `"BASETEN_API_KEY": "b"` to the patched env. Change the runpod test to `sync.PROVIDER_KEYS == {"RUNPOD_API_KEY": "k", "BASETEN_API_KEY": "b"}`. Add `"BASETEN_API_KEY"` and `"baseten_api_key"` to the `SENSITIVE` test, and `sync.WORKSPACES["custom-models-bootstrap"][1]["baseten_api_key"] == "b"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra/core && terraform init -backend=false && terraform test` and `cd scripts && python3 -m unittest tests.test_hcp_sync -v`
Expected: core fails (undeclared variable `baseten_api_key` or unknown resource); the Python tests fail on `PROVIDER_KEYS`.

- [ ] **Step 3: Implement**

- `variables.tf`: `variable "baseten_api_key"`, ephemeral, sensitive, the same description pattern as `runpod_api_key`.
- `provider_keys.tf`: secret `baseten-api-key` and its version (copy the Runpod pair). `resource "baseten_secret" "hf_access_token"` with `name = "hf_access_token"`, `value_wo = var.hf_token`, `value_wo_version = 1`, and a comment: rotate with `HF_TOKEN` and a higher version. Update the file header (Baseten is no longer "phase 4").
- `versions.tf`: provider `baseten` `~> 0.1.0`. `terraform init -backend=false` adds it to `.terraform.lock.hcl`; keep that change.
- `.envrc`: `export TF_VAR_baseten_api_key="${BASETEN_API_KEY:-}"`. `.env.example`: a `# Baseten` block with `BASETEN_API_KEY=` and 1 comment line (Baseten console, Settings, API keys; infra/core writes it to `baseten-api-key`; hcp-sync gives it to every workspace).
- `hcp-sync.py`: `baseten_api_key` in the core variables, `PROVIDER_KEYS`, `SENSITIVE`, the docstring.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd infra/core && terraform test` and `cd scripts && python3 -m unittest discover -s tests -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add infra/core .envrc .env.example scripts/hcp-sync.py scripts/tests/test_hcp_sync.py
git commit -m "feat(core): Baseten API key in Secret Manager and HCP; Hugging Face token as a Baseten secret"
```

---

### Task 4: LLM-A on `["vertex", "runpod", "baseten"]`

**Files:**
- Modify: `deployments/llm-a-gemma4-12b-vllm/main.tf`, `.terraform.lock.hcl`, `tests/gateway.tftest.hcl`, `tests/alerts.tftest.hcl`, `README.md`

**Interfaces:**
- Consumes: the facade with `baseten` (Task 2), output `baseten_config`.

- [ ] **Step 1: Write the failing tests**

Both test files: `mock_provider "baseten"` with the `id` default of Task 1. In `gateway.tftest.hcl`:

- `gateway_requires_api_key`: the path list becomes `["/baseten/v1/chat/completions", "/runpod/v1/chat/completions", "/v1/chat/completions", "/vertex/v1/chat/completions"]`.
- `outputs_for_scripts`: `output.platforms == tolist(["vertex", "runpod", "baseten"])`; `length(output.ui.platforms) == 3 && output.ui.platforms[2].id == "baseten"`; `output.ui.base_url` stays `"${output.gateway_url}/vertex"`.
- New run `baseten_flags`: `module.model.baseten_config.docker_server.start_command == "vllm serve --model=/models/weights --served-model-name=gemma-4-12b --max-model-len=32768 --host=0.0.0.0 --port=8000 --kv-cache-dtype=fp8"` (no `runai_streamer`, no `--revision`); `module.model.baseten_config.docker_server.server_port == 8000`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd deployments/llm-a-gemma4-12b-vllm && terraform init -backend=false && terraform test`
Expected: FAIL on the path list and on `output.platforms`.

- [ ] **Step 3: Implement**

`main.tf`: `platforms = ["vertex", "runpod", "baseten"]`. Add `baseten = { entrypoint = "vllm serve", extra_args = ["--kv-cache-dtype=fp8"] }` with the comment "the image ENTRYPOINT; L4 (Ada) has FP8. Weights come from BDN, pinned by the revision". Add `baseten` to `required_providers`. `terraform init -backend=false` updates the lock file; keep it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd deployments/llm-a-gemma4-12b-vllm && terraform test` and then `./scripts/check.py` from the repo root
Expected: all runs pass; check.py prints all roots ok.

- [ ] **Step 5: Write the README section**

New section "Baseten (2026-11-23)" after "Runpod (2026-11-23)":

1. One-time setup: link to the infra/README section of Task 5.
2. Expected `terraform plan`: create `baseten_model` (1 push), create the `secretAccessor` member of the proxy SA on `baseten-api-key`, update the proxy in place (`TARGETS`, new secret env var, timeout 600 s), a new API config with the `/baseten/` path, the gateway updated in place. No Vertex AI endpoint, no Runpod endpoint and no gateway is replaced.
3. Warning before the apply: the apply waits until the Baseten deployment is active (about 5 to 15 min). This starts 1 L4 replica, billed until `scale_down_delay` (300 s) ends.
4. After apply: a second `terraform plan` must say "No changes" (the first apply writes the autoscaling after the first push). Check `min_replica = 0` in the Baseten console (model, environment production, autoscaling). Then `./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm`, `./scripts/deploy.py status deployments/llm-a-gemma4-12b-vllm` (expect `baseten: deployed`), and a full `./scripts/ui-deploy.py`.
5. Test call: the curl of the "Test" section with `/baseten/v1/chat/completions`. Warning first: a call starts a Baseten replica.
6. A table to fill at the first cold call: the time to the first answer, and the HTTP status when it is above 600 s (gateway timeout).

- [ ] **Step 6: Commit**

```bash
git add deployments/llm-a-gemma4-12b-vllm
git commit -m "feat(llm-a): run on vertex, runpod and baseten"
```

---

### Task 5: Docs

**Files:**
- Modify: `infra/README.md`, `docs/backends.md`, `docs/scripts.md`, `docs/auth-and-ui.md`, `CLAUDE.md`, `.claude/skills/verify-gcp/SKILL.md`

- [ ] **Step 1: Write the docs**

- `infra/README.md`:
  - New section "Module: platform-baseten" after "Module: platform-runpod": inputs, options (Task 1 list), the port rule, the target values, the 600 s limit (decision 1), the push behavior (a config change pushes a new deployment; `DEACTIVATE` cleans up the old one), the phase 4 limits.
  - New section "Baseten setup (once)": make an account, make an API key (Settings, API keys), put it in `.env` as `BASETEN_API_KEY`, run `./scripts/hcp-sync.py`, apply `infra/core` (it creates `baseten-api-key` and the Baseten secret `hf_access_token`). Gated repos: set `hf_token_secret = "hf_access_token"`.
  - Line 450 ("Baseten comes in phase 4") and line 562 (the proxy keys): Baseten is supported now.
- `docs/backends.md`: Baseten as a proxy backend (use the `diagrams` skill and its render check if a diagram changes).
- `docs/scripts.md`: `hcp-sync.py` also writes `BASETEN_API_KEY`.
- `docs/auth-and-ui.md`: the Baseten hold note gets the 600 s gateway limit.
- `CLAUDE.md`: the `infra/modules/model/` bullet lists `platform-baseten`; the secrets table gets `BASETEN_API_KEY`.
- `.claude/skills/verify-gcp/SKILL.md`: a Baseten call bills a replica; the first call can take up to 600 s.

- [ ] **Step 2: Verify**

Run: `./scripts/check.py` and `terraform fmt -recursive -check`
Expected: all ok; fmt prints nothing.

- [ ] **Step 3: Commit**

```bash
git add infra/README.md docs CLAUDE.md .claude/skills/verify-gcp/SKILL.md
git commit -m "docs: Baseten platform (multi-platform phase 4)"
```

---

## What the user runs after this phase

1. Make the Baseten account and the API key. Put the key in `.env` as `BASETEN_API_KEY`. Today `.env` has no `BASETEN_API_KEY`.
2. Run `./scripts/hcp-sync.py --dry-run`, then `./scripts/hcp-sync.py`.
3. Apply `infra/core`. The plan must show only `baseten-api-key`, its version and the Baseten secret `hf_access_token`.
4. Run `terraform plan` in `deployments/llm-a-gemma4-12b-vllm`. Compare it with the README section "Baseten (2026-11-23)". Then apply (it starts 1 replica, see the warning).
5. Run a second `terraform plan` ("No changes"), `./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm`, `./scripts/deploy.py status deployments/llm-a-gemma4-12b-vllm` and a full `./scripts/ui-deploy.py`.
6. Make the first cold call to `/baseten/v1/chat/completions` and write the time into the README table.
