# Multi-platform Phase 1 (refactor, Vertex AI only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move LLM-A to a platform-neutral model module with `platforms = ["vertex"]`, with no change in behavior, so that Runpod and Baseten (phases 3 and 4) are one adapter each.

**Architecture:** A new facade module `infra/modules/model` takes 1 model spec and a platform list. It calls one adapter per platform (only `platform-vertex` in this phase), a new `gateway` module and the changed `cors-proxy`. The proxy routes by the first path segment (`/vertex/...`) and keeps the old paths on the default platform. `scripts/deploy.py` runs the post-apply step of each platform.

**Tech Stack:** Terraform `>= 1.11` (HCP Terraform remote runs, workspaces already set to `>= 1.11` by `scripts/hcp-sync.py`), providers `hashicorp/google` and `hashicorp/google-beta` `~> 8.10`, Python 3 standard library, `terraform test` with `mock_provider`.

**Spec:** `docs/specs/2026-11-22-multi-platform-design.md` (approved 2026-11-22). Read the sections "Design", "Migration of the existing deployments" and "Phases" (row 1).

## Global Constraints

- No change in behavior for LLM-A: the endpoint, the gateway, the gateway URL and the Slack alerts stay. The old path `/v1/chat/completions` keeps working.
- Names stay exactly: Vertex AI name `llm-a-gemma4-12b-vllm-vertex`, gateway ID `llm-a-gemma4-vertex`, gateway SA ID `llm-a-gemma4-vertex-gw`, proxy service `llm-a-gemma4-vertex-proxy`, HCP workspace `custom-models-llm-a-gemma4-12b-vllm-vertex`.
- Phase 1 supports only the platform id `vertex`. The facade rejects `baseten` and `runpod` until phases 3 and 4 add their adapters.
- LLM-B, STT-A and TTS-A keep their behavior. The only change in LLM-B and STT-A is the `cors-proxy` call (`target` → `targets`, Task 2). TTS-A does not change. `infra/modules/vertex-model` keeps its variables and outputs.
- `required_version = ">= 1.11"` in the new modules and in the LLM-A root. The other roots keep `>= 1.7`.
- Provider versions `~> 8.10` for `google` and `google-beta`. Keep `.terraform.lock.hcl` tracked.
- Scripts: Python 3 standard library only, in `scripts/`. A new runnable script loads `.env` itself (copy `load_env()` and `env_like_envrc()` from `scripts/vertex.py`). No shell scripts.
- The agent runs only `terraform fmt`, `terraform init -backend=false`, `terraform validate`, `terraform test`, `./scripts/check.py`, and Python unit tests. `terraform plan` and `apply` against HCP, `scripts/deploy.py`, `scripts/vertex.py` and test calls are run by the user.
- Docs prose is in Simplified Technical English.
- Never print `.env` values.

## Plan decisions (not in the spec)

1. **Direction of the Vertex AI wrapper.** The spec says `platform-vertex` takes the code of `vertex-model`, and `vertex-model` becomes a thin wrapper. This plan does the reverse: `platform-vertex` is the thin adapter, and it calls `vertex-model` unchanged. The result is the same (no copy of code, LLM-B and STT-A untouched), and phase 1 moves fewer resources. Phase 6 can fold `vertex-model` into `platform-vertex` when the last direct caller is gone.
2. **`spec.weights.revision` is optional in phase 1.** Vertex AI does not use it. Phase 3 makes it required when a non-vertex platform is in the list.
3. **The order of the vLLM flags changes** (`spec.args`, then `platform_options.vertex.extra_args`). vLLM does not depend on the flag order. The uploaded model in Vertex AI changes only after the next `undeploy` and `deploy`.

## Review Focus

1. A path that is only the prefix (`/vertex`, no route) must go to the vertex target with the path `/`, not to the default with `/vertex`. Test in Task 2.
2. A segment that only starts like a platform id (`/vertexx/v1/x`) must go to the default platform with the full path. Test in Task 2.
3. A query string must stay on the upstream URL for an `append_path` target (`/vertex/v1/x?a=1` → `<url>/v1/x?a=1`). Test in Task 2.
4. A missing provider key env var must give HTTP 502 with CORS headers, not a crash or a hang. Test in Task 2.
5. An empty, duplicated or unsupported platform list must fail at plan with a clear message. Test in Task 5.

---

### Task 1: Secret env vars in `model-service`

**Files:**
- Modify: `infra/modules/model-service/variables.tf`, `infra/modules/model-service/main.tf`
- Test: `infra/modules/model-service/tests/model_service.tftest.hcl`

**Interfaces:**
- Produces: variable `secret_env` (`map(string)`, default `{}`): env var name → Secret Manager secret ID (in the same project). Each entry becomes a Cloud Run env var with `value_source.secret_key_ref { secret = <id>, version = "latest" }`, and a `google_secret_manager_secret_iam_member.secret_env[<name>]` with `roles/secretmanager.secretAccessor` for the service SA.

- [ ] **Step 1: Write the failing test** `run "secret_env_reads_secret_manager"` (command `apply`, `secret_env = { RUNPOD_API_KEY = "runpod-api-key" }`). Assert: the container has an env named `RUNPOD_API_KEY` whose `value_source[0].secret_key_ref[0].secret == "runpod-api-key"` and `version == "latest"`; `google_secret_manager_secret_iam_member.secret_env["RUNPOD_API_KEY"].role == "roles/secretmanager.secretAccessor"` and its member is the service SA. Add `run "no_secret_env_by_default"`: `length(google_secret_manager_secret_iam_member.secret_env) == 0`.
- [ ] **Step 2: Run** `cd infra/modules/model-service && terraform init -backend=false && terraform test`. Expected: FAIL (unknown variable `secret_env`).
- [ ] **Step 3: Implement** the variable, a second `dynamic "env"` block over `var.secret_env`, and the IAM member resource (`for_each = var.secret_env`). Update the `env` description: plain values only; secrets go in `secret_env`.
- [ ] **Step 4: Run** `terraform test`. Expected: all runs pass.
- [ ] **Step 5: Commit** `git commit -m "feat(model-service): optional secret env vars from Secret Manager"`

### Task 2: Multi-target CORS proxy

**Files:**
- Modify: `infra/modules/cors-proxy/cors_proxy.py`, `variables.tf`, `main.tf`, `outputs.tf` (if needed)
- Create: `infra/modules/cors-proxy/tests/__init__.py`, `infra/modules/cors-proxy/tests/test_cors_proxy.py`
- Modify: `infra/modules/cors-proxy/tests/cors_proxy.tftest.hcl`, `scripts/check.py`

**Interfaces:**
- Consumes: `model-service.secret_env` (Task 1).
- Produces (Terraform): variables `targets` (`map(object({ url = string, append_path = bool, auth = string }))`), `default_platform` (`string`), `secret_env` (`map(string)`, default `{}`), `timeout` (`string`, default `"300s"`). Variable `target` is removed. Validations: every `url` starts with `https://`; `default_platform` is a key of `targets`; `auth` is `google`, `baseten` or `runpod`. Env vars of the service: `TARGETS = jsonencode(var.targets)`, `DEFAULT = var.default_platform`. `google_project_iam_member.predict` gets `count = anytrue([for t in values(var.targets) : t.auth == "google"]) ? 1 : 0`, with `moved { from = google_project_iam_member.predict  to = google_project_iam_member.predict[0] }` in `main.tf`. New output `env` = `{ TARGETS = <json>, DEFAULT = <id> }` (the plain env vars, for tests).
- Produces (Python, in `cors_proxy.py`): `load_targets(environ: dict) -> tuple[dict, str]`, `pick(path: str, targets: dict, default: str) -> tuple[str, str]` (platform id, path for upstream), `upstream_url(target: dict, rest: str) -> str`, `auth_header(auth: str, environ: dict, google_token) -> str` (`google_token` is a zero-argument callable). The server start moves under `if __name__ == "__main__":`, so the tests can import the file. The handler forwards `GET` and `POST`.

- [ ] **Step 1: Write the failing Python tests** in `tests/test_cors_proxy.py`. Import the module with `importlib.util.spec_from_file_location("cors_proxy", <module folder>/cors_proxy.py)`. Targets in the tests: `{"vertex": {"url": "https://v/x:rawPredict", "append_path": False, "auth": "google"}, "runpod": {"url": "https://r", "append_path": True, "auth": "runpod"}}`, default `vertex`.
  - `test_prefix_selects_target`: `pick("/runpod/v1/chat/completions", T, "vertex") == ("runpod", "/v1/chat/completions")`
  - `test_old_path_uses_default`: `pick("/v1/chat/completions", T, "vertex") == ("vertex", "/v1/chat/completions")`
  - `test_bare_prefix`: `pick("/runpod", T, "vertex") == ("runpod", "/")` (Review Focus 1)
  - `test_similar_segment_is_not_a_prefix`: `pick("/runpodx/v1", T, "vertex") == ("vertex", "/runpodx/v1")` (Review Focus 2)
  - `test_query_string_kept`: `pick("/runpod/v1/x?a=1", ...)` gives rest `/v1/x?a=1`, and `upstream_url(T["runpod"], "/v1/x?a=1") == "https://r/v1/x?a=1"` (Review Focus 3)
  - `test_fixed_url_ignores_rest`: `upstream_url(T["vertex"], "/v1/chat/completions") == "https://v/x:rawPredict"`
  - `test_google_auth_uses_token`: `auth_header("google", {}, lambda: "tok") == "Bearer tok"`
  - `test_key_auth_reads_env`: `auth_header("runpod", {"RUNPOD_API_KEY": "k"}, None) == "Bearer k"`
  - `test_missing_key_raises`: `auth_header("runpod", {}, None)` raises `KeyError` (Review Focus 4: the handler turns any error before the upstream call into 502 with CORS headers, as today)
  - `test_load_targets_rejects_unknown_default`: `load_targets({"TARGETS": json.dumps(T), "DEFAULT": "x"})` raises `ValueError`
- [ ] **Step 2: Run** `cd infra/modules/cors-proxy && python3 -m unittest tests.test_cors_proxy`. Expected: FAIL (functions not defined).
- [ ] **Step 3: Implement** the 4 functions and the handler changes. Read `TARGETS` and `DEFAULT` once at start (in the `__main__` block). Keep: CORS headers on every answer, `OPTIONS` 204 with `Content-Length: 0`, chunked streaming, 502 JSON with CORS on any error before the upstream answer. The `auth_header` call is inside the `try` that makes the 502.
- [ ] **Step 4: Run** the Python tests. Expected: PASS.
- [ ] **Step 5: Change the Terraform tests** in `cors_proxy.tftest.hcl`: replace `target` with `targets = { vertex = { url = "https://dns/v1/projects/p/locations/us-central1/endpoints/1:rawPredict", append_path = false, auth = "google" } }` and `default_platform = "vertex"`. Keep `only_gateway_calls_and_proxy_predicts` (use `predict[0]`). Add `run "targets_must_be_https"` (an `http://` url, `expect_failures = [var.targets]`), `run "default_must_be_a_target"` (`default_platform = "x"`, `expect_failures = [var.default_platform]`), and `run "no_predict_role_without_google_target"` (only a `runpod` target with `secret_env = { RUNPOD_API_KEY = "runpod-api-key" }`: `length(google_project_iam_member.predict) == 0`).
- [ ] **Step 6: Implement** the Terraform changes. The module passes `timeout` and `secret_env` to `model-service`.
- [ ] **Step 7: Make `scripts/check.py` run module Python tests.** In `py_tests(d)`, also yield `d` itself when `d/tests/test_*.py` exists, and run `py_tests` for every root (not only for `deployments/*`). Update the docstring.
- [ ] **Step 8: Run** `./scripts/check.py infra/modules/cors-proxy`. Expected: `python tests (.)`, `validate` and `test` are `ok`.
- [ ] **Step 9: Commit** `git commit -m "feat(cors-proxy): several targets routed by the first path segment"`

Note: LLM-A, LLM-B and STT-A still pass `target`. They break `validate` until Task 6 (LLM-A). For LLM-B and STT-A, add a one-line change in this task: `targets = { vertex = { url = <their current target>, append_path = <true for /invoke, else false>, auth = "google" } }` and `default_platform = "vertex"`. Their gateways keep their old paths, so their behavior does not change. Run `./scripts/check.py deployments/llm-b-qwen35-9b-fastapi deployments/stt-a-qwen3-asr-diar-vertex`. Expected: all `ok`.

### Task 3: Gateway module

**Files:**
- Create: `infra/modules/gateway/{main.tf,variables.tf,outputs.tf,versions.tf}`, `infra/modules/gateway/tests/gateway.tftest.hcl`

**Interfaces:**
- Produces: variables `project_id`, `region` (the gateway region), `gateway_id` (max 27 chars, validation), `backend_url` (https), `platforms` (`list(string)`, ordered, first = default), `routes` (`list(string)`, each starts with `/`), `methods` (`list(string)`, default `["post"]`), `deadlines` (`map(number)`, key = platform id), `extra_paths` (`map(object({ backend_url = string, methods = list(string), deadline = number }))`, default `{}`). Outputs: `gateway_url` (`https://<default_hostname>`), `gateway_id`, `gateway_region`, `api_config` (full ID), `service_account_email`, `address` (the string `"google_api_gateway_gateway.this"`), `openapi` (the object, for tests).
- Resources: copy the 3 resources from `deployments/llm-a-gemma4-12b-vllm-vertex/gateway.tf` (`google_service_account.this` with `account_id = "${var.gateway_id}-gw"`, `google_api_gateway_api_config.this` with `create_before_destroy`, `google_api_gateway_gateway.this`). Use `google-beta` where the source does.
- OpenAPI rules: the spec section "Gateway module", items 1 to 5. Each operation has its own `x-google-backend = { address, path_translation = "APPEND_PATH_TO_ADDRESS", deadline }`. No top-level `x-google-backend`. Global `security = [{ api_key = [] }]` and `securityDefinitions.api_key = { type = "apiKey", name = "x-api-key", in = "header" }`, as today.

- [ ] **Step 1: Write the failing tests** (`mock_provider "google"`, `mock_provider "google-beta"`, variables: `gateway_id = "llm-a-gemma4-vertex"`, `backend_url = "https://proxy"`, `platforms = ["vertex"]`, `routes = ["/v1/chat/completions"]`, `deadlines = { vertex = 300 }`):
  - `run "paths_per_platform_plus_old"`: `keys(output.openapi.paths) == ["/v1/chat/completions", "/vertex/v1/chat/completions"]`
  - `run "every_operation_calls_backend_with_append"`: every non-`options` operation has `x-google-backend.address == "https://proxy"`, `path_translation == "APPEND_PATH_TO_ADDRESS"`, `deadline == 300`; `!contains(keys(output.openapi), "x-google-backend")`
  - `run "api_key_and_cors_preflight"`: the 4 asserts of today's `deployments/llm-a-gemma4-12b-vllm-vertex/tests/gateway.tftest.hcl` (`gateway_requires_api_key`), against `output.openapi`
  - `run "operation_ids_unique"`: the list of all `operationId` values has no duplicates
  - `run "deadline_per_platform"`: with `platforms = ["vertex", "runpod"]` and `deadlines = { vertex = 300, runpod = 1200 }`: `/runpod/...` post deadline is 1200, and the old path has 300 (the default platform)
  - `run "extra_paths_get_prefix_and_own_backend"`: `extra_paths = { "/v1beta/files" = { backend_url = "https://api", methods = ["get"], deadline = 60 } }` gives `/v1beta/files` and `/vertex/v1beta/files`, each with a `get` operation to `https://api`, plus `options`
  - `run "sa_id_max_30"`: `length(google_service_account.this.account_id) <= 30`
- [ ] **Step 2: Run** `cd infra/modules/gateway && terraform init -backend=false && terraform test`. Expected: FAIL (no configuration).
- [ ] **Step 3: Implement** the module. Build `paths` in `locals` with `merge` over platforms × routes, the old routes, and the extra paths.
- [ ] **Step 4: Run** `terraform test`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(gateway): gateway module with a path prefix per platform"`

### Task 4: `platform-vertex` adapter

**Files:**
- Create: `infra/modules/platform-vertex/{main.tf,variables.tf,outputs.tf,versions.tf}`, `infra/modules/platform-vertex/tests/platform_vertex.tftest.hcl`

**Interfaces:**
- Consumes: `infra/modules/vertex-model` unchanged, called as `module "engine"`.
- Produces: variables `project_id`, `region`, `name`, `spec` (`any`; the facade owns the type), `options` (`any`, default `{}`). Outputs:
  - `target`: `{ id = "vertex", label = "Vertex AI", url, append_path, auth = "google", cold_start = "retry-429", deadline = 300, post_apply = "vertex" }`. `url` is `https://<dns>/v1/projects/<p>/locations/<r>/endpoints/<id>:rawPredict` with `append_path = false` when `options.predict_route` is set, else the same base with `/invoke` and `append_path = true`.
  - `vertex` (pass-through of `module.engine.vertex`), `endpoint_id`, `endpoint_dns`, `service_account_email`.
- Mapping to `vertex-model` (read with `try(var.options.<x>, <default>)`):

| `vertex-model` variable | Value |
|---|---|
| `name` | `options.name`, else `var.name` |
| `image` | stock: `<region>-docker.pkg.dev/<project>/dockerhub/<image>`, with `library/` added when the image has no `/`. own: `<region>-docker.pkg.dev/<project>/models/<own>` |
| `args` | `[for a in concat(spec.args, options.extra_args or []) : replace(a, "{model}", "$(AIP_STORAGE_URI)")]` |
| `env` | `merge(spec.env or {}, { HF_HUB_OFFLINE = "1" }, options.env or {})` |
| `port`, `health_route` | `spec.port` (default 8080), `spec.health_route` |
| `predict_route`, `invoke_routes` | `options.predict_route` (default null); `invoke_routes = options.predict_route == null` |
| `machine_type` | `options.machine_type`, default `"g2-standard-8"` |
| `accelerator_type`, `accelerator_count` | `"NVIDIA_L4"` and 1 when `spec.gpu == "L4"`; null when `spec.gpu` is null. Any other value fails a precondition |
| `shared_memory_size_mb`, `deployment_timeout` | from `options` (defaults: null, `"1800s"`) |
| `max_replica_count` | `spec.max_replicas` (default 1) |
| `idle_scaledown_period` | `"${spec.idle_seconds}s"` (default 300) |
| `weights_bucket`, `weights_dir` | `"<project>-models"` and `spec.weights.gcs_dir` when it is set, else null |

- [ ] **Step 1: Write the failing tests** (`mock_provider "google"`), with the LLM-A spec and options from the spec section "Deployment folder after the change" (`platform_options.vertex` only):
  - `run "same_upload_as_today"`: `output.vertex.model_upload.model.containerSpec.args` contains `"--model=$(AIP_STORAGE_URI)"`, `"--load-format=runai_streamer"` and `"--kv-cache-dtype=fp8"`; `imageUri == "us-central1-docker.pkg.dev/p/dockerhub/vllm/vllm-openai:v0.33.0"`; `predictRoute == "/v1/chat/completions"`; env has `HF_HUB_OFFLINE = "1"`; `output.vertex.name == "llm-a-gemma4-12b-vllm-vertex"`
  - `run "scale_to_zero"`: `minReplicaCount == 0`, `maxReplicaCount == 1`, `idleScaledownPeriod == "300s"`, `acceleratorType == "NVIDIA_L4"`
  - `run "target_raw_predict"`: `output.target.append_path == false`, `endswith(output.target.url, ":rawPredict")`, `output.target.post_apply == "vertex"`, `output.target.auth == "google"`
  - `run "target_invoke_without_predict_route"`: no `predict_route` in options: `output.target.append_path == true`, `endswith(output.target.url, "/invoke")`
  - `run "stock_image_without_namespace"`: `spec.image = { stock = "python:3.13" }` gives `.../dockerhub/library/python:3.13`
  - `run "own_image"`: `spec.image = { own = "llm-b:1" }` gives `us-central1-docker.pkg.dev/p/models/llm-b:1`
- [ ] **Step 2: Run** `cd infra/modules/platform-vertex && terraform init -backend=false && terraform test`. Expected: FAIL.
- [ ] **Step 3: Implement** the module (`locals` for the mapping, one `module "engine"`).
- [ ] **Step 4: Run** `terraform test`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(platform-vertex): Vertex AI adapter with the common target output"`

### Task 5: `model` facade

**Files:**
- Create: `infra/modules/model/{main.tf,variables.tf,outputs.tf,versions.tf}`, `infra/modules/model/tests/model.tftest.hcl`

**Interfaces:**
- Consumes: `platform-vertex` (Task 4), `gateway` (Task 3), `cors-proxy` (Task 2).
- Produces: variables `project_id`, `region`, `gateway_region`, `name`, `gateway_id`, `platforms` (`list(string)`), `spec` (the typed object from the spec section "Input types of the facade", with `weights.revision = optional(string)` (plan decision 2) and `idle_seconds = optional(number, 300)`), `platform_options` (`any`, default `{}`).
- Validation of `platforms`: not empty; no duplicates; every id is in `local.supported = ["vertex"]`. The message names the supported ids.
- Calls: `module "vertex"` (`count = contains(var.platforms, "vertex") ? 1 : 0`, `options = try(var.platform_options.vertex, {})`), `module "cors_proxy"` (`name = "${var.gateway_id}-proxy"`, image `<region>-docker.pkg.dev/<project>/dockerhub/library/python:3.13.9-slim`, `targets` and `default_platform = var.platforms[0]`, `timeout = "${max(deadlines)}s"`), `module "gateway"` (`backend_url = module.cors_proxy.url`, `routes = var.spec.routes`, `deadlines` from the targets).
- Outputs: `platforms` (ordered ids), `targets` (map id → target), `gateway_url`, `gateway_id`, `gateway_region`, `api_config`, `gateway_address` (`"module.gateway.${module.gateway.address}"`), `openapi`, `vertex` (`try(module.vertex[0].vertex, null)`), `vertex_endpoint_id`, `vertex_endpoint_dns` (null without vertex).

- [ ] **Step 1: Write the failing tests** (mock `google` and `google-beta`, the LLM-A inputs):
  - `run "vertex_only"`: `output.platforms == ["vertex"]`, `keys(output.targets) == ["vertex"]`, `output.vertex != null`
  - `run "proxy_gets_targets_and_default"`: `jsondecode(module.cors_proxy.env.TARGETS).vertex.auth == "google"`, `jsondecode(module.cors_proxy.env.TARGETS).vertex.append_path == false`, `module.cors_proxy.env.DEFAULT == "vertex"`
  - `run "gateway_paths"`: `keys(output.openapi.paths) == ["/v1/chat/completions", "/vertex/v1/chat/completions"]`
  - `run "rejects_empty"`: `platforms = []`, `expect_failures = [var.platforms]` (Review Focus 5)
  - `run "rejects_duplicates"`: `platforms = ["vertex", "vertex"]`, `expect_failures = [var.platforms]` (Review Focus 5)
  - `run "rejects_unsupported"`: `platforms = ["runpod"]`, `expect_failures = [var.platforms]` (Review Focus 5)
  - `run "names_unchanged"`: `output.vertex.name == "llm-a-gemma4-12b-vllm-vertex"`, `output.gateway_id == "llm-a-gemma4-vertex"`
- [ ] **Step 2: Run** `cd infra/modules/model && terraform init -backend=false && terraform test`. Expected: FAIL.
- [ ] **Step 3: Implement** the facade. `local.targets = merge(contains(var.platforms, "vertex") ? { vertex = module.vertex[0].target } : {})`. Later phases add one entry each.
- [ ] **Step 4: Run** `terraform test`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(model): facade module that deploys one model spec to a list of platforms"`

### Task 6: Move LLM-A to the facade

**Files:**
- Modify: `deployments/llm-a-gemma4-12b-vllm-vertex/main.tf`, `outputs.tf`, `alerts.tf`
- Delete: `deployments/llm-a-gemma4-12b-vllm-vertex/gateway.tf`, `cors_proxy.tf`
- Create: `deployments/llm-a-gemma4-12b-vllm-vertex/moved.tf`
- Modify: `deployments/llm-a-gemma4-12b-vllm-vertex/tests/gateway.tftest.hcl`, `tests/alerts.tftest.hcl`

**Interfaces:**
- Consumes: the facade (Task 5).
- Produces: root outputs with the same names as today, so the scripts keep working: `endpoint_id`, `endpoint_dns`, `vertex`, `gateway_url`, `gateway_id`, `gateway_region`, `api_config`, `ui` (unchanged value; `base_url` stays the gateway root). New root outputs: `platforms`, `targets`, `gateway_address` (`"module.model.${module.model.gateway_address}"`).

- [ ] **Step 1: Read the current state addresses.** Ask the user to run `cd deployments/llm-a-gemma4-12b-vllm-vertex && direnv exec . terraform state list` (read-only) and paste the list. Do not guess the list.
- [ ] **Step 2: Change the tests first.** In `tests/gateway.tftest.hcl`: assert on `module.model.openapi`; paths are `["/v1/chat/completions", "/vertex/v1/chat/completions"]`; every post operation calls `module.model` proxy with `APPEND_PATH_TO_ADDRESS`; keep the API key and preflight asserts; SA ID ≤ 30. In `tests/alerts.tftest.hcl`: `module.scale_alerts[0]`. Add `run "outputs_for_scripts"`: `output.gateway_address == "module.model.module.gateway.google_api_gateway_gateway.this"`, `output.platforms == ["vertex"]`, `output.vertex.name == "llm-a-gemma4-12b-vllm-vertex"`.
- [ ] **Step 3: Run** `cd deployments/llm-a-gemma4-12b-vllm-vertex && terraform init -backend=false && terraform test`. Expected: FAIL.
- [ ] **Step 4: Rewrite `main.tf`** as the spec section "Deployment folder after the change", with `local.platforms = ["vertex"]`, `gateway_region = var.gateway_region`, no `platform_options.baseten` or `runpod`, and `required_version = ">= 1.11"`. Delete `gateway.tf` and `cors_proxy.tf`. `alerts.tf`: `count = contains(local.platforms, "vertex") ? 1 : 0` and `module.model.vertex_endpoint_id`.
- [ ] **Step 5: Write `moved.tf`.** One `moved` block per resource from Step 1. The expected map (check it against Step 1):

| From | To |
|---|---|
| `module.model.google_service_account.this` | `module.model.module.vertex[0].module.engine.google_service_account.this` |
| `module.model.google_storage_bucket_iam_member.weights[0]` | `module.model.module.vertex[0].module.engine.google_storage_bucket_iam_member.weights[0]` |
| `module.model.google_vertex_ai_endpoint.this` | `module.model.module.vertex[0].module.engine.google_vertex_ai_endpoint.this` |
| `module.cors_proxy` | `module.model.module.cors_proxy` |
| `google_service_account.gateway` | `module.model.module.gateway.google_service_account.this` |
| `google_api_gateway_api_config.this` | `module.model.module.gateway.google_api_gateway_api_config.this` |
| `google_api_gateway_gateway.this` | `module.model.module.gateway.google_api_gateway_gateway.this` |
| `module.scale_alerts` | `module.scale_alerts[0]` |

- [ ] **Step 6: Run** `terraform validate && terraform test`. Expected: PASS. If `validate` rejects a `moved` block, change only that block (for example, move each resource of a module instead of the module) and say why in a comment.
- [ ] **Step 7: Run** `./scripts/check.py deployments/llm-a-gemma4-12b-vllm-vertex`. Expected: all `ok`.
- [ ] **Step 8: Commit** `git commit -m "refactor(llm-a): use the model module with platforms = [vertex]"`

### Task 7: Deploy script and script updates

**Files:**
- Create: `scripts/platforms/__init__.py`, `scripts/platforms/vertex.py`, `scripts/deploy.py`, `scripts/tests/__init__.py`, `scripts/tests/test_deploy.py`
- Modify: `scripts/vertex.py`, `scripts/ui-deploy.py`, `scripts/gateway-streaming.py`, `scripts/check.py`

**Interfaces:**
- Produces in `scripts/platforms/vertex.py` (library, no `.env` loading): `deploy(d: pathlib.Path) -> None`, `undeploy(d: pathlib.Path) -> None`, `deployed(d: pathlib.Path) -> bool`. They read `terraform output -json vertex` in `d` and get a token with `gcloud auth print-access-token`. They contain the current logic of `scripts/vertex.py` (`call`, `wait`, `deployed_ids`, `warm_cache`, `drop_nulls`, the reuse of an uploaded model), with module state instead of globals. The "already deployed" message says `./scripts/deploy.py undeploy <dir> --platform vertex`.
- Produces in `scripts/deploy.py`: `select(platforms: list[str], targets: dict, only: str | None) -> list[dict]` (targets in the order of `platforms`; with `only`, the one target; an unknown `only` exits with `unknown platform <x>; this model has: <ids>`), and the CLI `deploy|undeploy|status <deployment> [--platform <id>]` from the spec section "Deploy script". `status` prints `<id>: deployed` or `<id>: not deployed` (a target without `post_apply` is deployed when it is in `targets`). After `deploy` and `undeploy`, it runs `ui-deploy.py --config-only`.
- `scripts/vertex.py` keeps its CLI (`deploy|undeploy deployments/<name>`) and calls `platforms.vertex`. LLM-B and STT-A have no `targets` output yet, so they keep using it.
- `scripts/ui-deploy.py`: `has_deployed_model(d, out_tf)` calls `platforms.vertex.deployed(d)` and keeps its current "keep the tab on error" rule.
- `scripts/gateway-streaming.py`: the import address is `terraform output -raw gateway_address` when the output exists, else `google_api_gateway_gateway.this` (TTS-A, LLM-B, STT-A).

- [ ] **Step 1: Write the failing tests** in `scripts/tests/test_deploy.py` (import `deploy.py` with `importlib.util.spec_from_file_location`):
  - `test_select_all_in_order`: `select(["vertex", "runpod"], {"runpod": R, "vertex": V}, None) == [V, R]`
  - `test_select_one`: `select(["vertex", "runpod"], T, "runpod") == [R]`
  - `test_select_unknown_exits`: `select(["vertex"], {"vertex": V}, "baseten")` raises `SystemExit` with `"unknown platform baseten; this model has: vertex"`
  - `test_gateway_address_fallback`: a function `gateway_address(outputs: dict) -> str` in `gateway-streaming.py` returns `outputs["gateway_address"]["value"]` when it exists, else `"google_api_gateway_gateway.this"` (import that file the same way)
- [ ] **Step 2: Run** `cd scripts && python3 -m unittest tests.test_deploy`. Expected: FAIL.
- [ ] **Step 3: Implement** `platforms/vertex.py`, `deploy.py`, the thin `vertex.py`, and the changes to `ui-deploy.py` and `gateway-streaming.py`. `deploy.py` adds `scripts/` to `sys.path` and imports `platforms.<post_apply>` with `importlib.import_module`.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Run `scripts/tests` from `scripts/check.py`**: after the roots, run `python3 -m unittest discover -s tests` in `scripts/` when `scripts/tests` exists, as a step named `python tests (scripts)`.
- [ ] **Step 6: Run** `./scripts/check.py`. Expected: every root and `python tests (scripts)` are `ok`.
- [ ] **Step 7: Commit** `git commit -m "feat(scripts): deploy.py runs the post-apply step of each platform"`

### Task 8: Docs and the user's plan check

**Files:**
- Modify: `infra/README.md`, `docs/README.md`, `CLAUDE.md`, `deployments/llm-a-gemma4-12b-vllm-vertex/README.md`
- Modify where they name `vertex.py` for LLM-A or the LLM-A `gateway.tf`: find them with `grep -rn "vertex.py\|gateway.tf\|cors_proxy.tf" docs infra .claude/skills deployments/llm-a-gemma4-12b-vllm-vertex CLAUDE.md`

- [ ] **Step 1: `infra/README.md`**: add sections "Module: model (platforms)", "Module: platform-vertex", "Module: gateway". Change "Module: cors-proxy" (targets, prefix routing, `secret_env`). Add `scripts/deploy.py` usage with placeholders. Link to the spec.
- [ ] **Step 2: `docs/README.md`**: the gateway and streaming guide shows the `/vertex/` prefix next to the old path. The scripts guide lists `deploy.py`. Update the Mermaid diagrams with the `diagrams` skill.
- [ ] **Step 3: `CLAUDE.md`**: the architecture list names `infra/modules/model`, `platform-vertex`, `gateway`, and `scripts/deploy.py`. Keep it short.
- [ ] **Step 4: LLM-A `README.md`**: deploy with `./scripts/deploy.py deploy deployments/llm-a-gemma4-12b-vllm-vertex`; a test call on `/vertex/v1/chat/completions` next to the old path; the expected result of the first `terraform plan` after this change (Step 6).
- [ ] **Step 5: Run** `./scripts/check.py` and `terraform fmt -recursive -check`. Expected: all `ok`.
- [ ] **Step 6: Ask the user to run the plan** (the agent does not run it): `cd deployments/llm-a-gemma4-12b-vllm-vertex && direnv exec . terraform init && direnv exec . terraform plan`. Expected:
  - The 8 moves of Task 6, Step 5.
  - 1 new API config (new paths) and 1 old API config destroyed.
  - In-place updates: the gateway (`api_config`) and the proxy Cloud Run service (env `TARGETS` and `DEFAULT`, new args).
  - **No** replace or destroy of `google_vertex_ai_endpoint`, `google_api_gateway_gateway` or any service account.
  If the plan shows anything else, stop and fix the `moved` blocks before the user applies.
- [ ] **Step 7: After the user's apply**, ask the user to run `./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm-vertex` (it does nothing when the gateway still streams), then one test call on the old path and one on `/vertex/v1/chat/completions` (an LLM call starts a GPU replica: about $1.34 per hour).
- [ ] **Step 8: Commit** `git commit -m "docs: model module, gateway module and deploy.py (multi-platform phase 1)"`

## Done when (phase 1 of the spec)

- `./scripts/check.py` passes for every root, the module Python tests and `scripts/tests`.
- The user's `terraform plan` for LLM-A shows only the expected changes (Task 8, Step 6).
- After the apply, the old path and `/vertex/v1/chat/completions` both answer through the gateway with the shared API key.
