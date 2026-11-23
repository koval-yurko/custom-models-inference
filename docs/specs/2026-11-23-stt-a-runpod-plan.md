# STT-A on Runpod (phase 6, STT-A part) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Status 2026-11-23: implemented on the card branch. `./scripts/check.py` is green. Apply, the weights copy and the test calls are open ("What the user runs after this phase").

**Goal:** STT-A runs on Vertex AI and on Runpod at the same time. `<gateway>/runpod/v1beta/interactions` and `<gateway>/runpod/v1beta/files/<id>/transcribe` reach a Runpod load balancing endpoint that scales to 0. The old paths and `/vertex/...` keep working. The deployment folder gets the platform-neutral name `deployments/stt-a-qwen3-asr-diar`.

**Architecture:** STT-A moves into the `model` facade (`infra/modules/model`) with `platforms = ["vertex", "runpod"]`, as LLM-A did in phase 1. `moved` blocks keep the Vertex AI endpoint, the CORS proxy and the gateway. The Runpod adapter learns 2 things: own images from Artifact Registry (a `runpod_registry` made by `infra/core`) and a Runpod network volume for the weights. A new script `scripts/runpod-weights.py` copies the weights from the GCS weights bucket to the volume through the Runpod S3 API, so both platforms load the same bytes. `stt_api` calls the GPU through the CORS proxy and sends signed HTTPS audio URLs, so the GPU service needs no GCP credentials. The proxy turns a Runpod wait longer than about 280 s into HTTP 429, so the clients retry.

**Tech Stack:** Terraform >= 1.11 (`terraform test` with `mock_provider`), providers `hashicorp/google ~> 8.10`, `runpod/runpod ~> 2.0`. Python 3 standard library (`unittest`) for scripts, `stt_api` and the proxy. `speech_engine` keeps its pinned packages.

**Spec:** `docs/specs/2026-11-22-multi-platform-design.md` (sections "Container contract for own images (phase 6)", "Secrets and keys", "Migration of the existing deployments", "Phases" row 6). Phase 3 plan (Runpod adapter): `docs/specs/2026-11-23-multi-platform-phase3-plan.md`. STT-A design: `docs/specs/2026-11-21-stt-a-design.md`.

## User decisions (2026-11-23, card "stt-a-qwen3-asr-diar-vertex")

| Item | Decision | Rejected |
|---|---|---|
| Weights on Runpod | Runpod network volume. A separate script loads the data into it | Hugging Face download at each start; weights in the image |
| Image pull | Read-only Artifact Registry key in `infra/core`, as `runpod_registry` | Copy of the image to GHCR or Docker Hub |
| Scope | Full facade move with `moved` blocks. LLM-B and the removal of `vertex-model` stay for a later card | A Runpod copy next to the current STT-A files |
| Cold start above the 300 s gateway deadline | The proxy stops at about 280 s and answers 429 with `Retry-After: 30` | Accept a 504 and measure first |
| Folder name | `deployments/stt-a-qwen3-asr-diar` (platform-neutral) | — |

## Global Constraints

- The Vertex AI endpoint, the gateway and every service account stay. The plan of the user must show no replace of `google_vertex_ai_endpoint`, `google_api_gateway_gateway` or a service account. A new API config is expected (new paths).
- The HCP workspace keeps its name `custom-models-stt-a-qwen3-asr-diar-vertex`, so the state stays. Only the folder and the working directory in `scripts/hcp-sync.py` change. `infra/core` does the same with its old workspace name.
- `workers_min = 0` on Runpod. `max_replicas` stays 1 on both platforms.
- No key in git, `models.json` or the browser. The Runpod S3 keys stay in `.env` only: only the script uses them. The Artifact Registry pull key is in the `infra/core` state (accepted in the design, read-only).
- The GPU image is the same on both platforms. Platform differences come from env only (`PORT`, `MODEL`, `SETUP_PLATFORM`).
- Scripts: Python 3 standard library only. Each script loads `.env` itself (copy `load_env()` from `scripts/vertex.py`). No `direnv exec` in front of a script.
- The agent does not run apply, deploy, the weights copy or test calls. It verifies with `./scripts/check.py`.
- Docs prose in Simplified Technical English.

## Review Focus

1. A missing or wrong `moved` block replaces the Vertex AI endpoint or the gateway. Then the endpoint ID or the gateway URL changes. Check: `terraform test` asserts the new addresses, and the user reads the plan before apply (step "Plan check").
2. The signed audio URL must not open an SSRF hole in `speech_engine`. It accepts only `https://storage.googleapis.com/<AUDIO_BUCKET>/...` and `gs://<AUDIO_BUCKET>/...`. Test: `test_logic.py` (other host, other bucket, `http://`, a path with `..`).
3. A good Runpod answer must arrive in full. The proxy maps only a timeout before the first response byte to 429, never a slow body. Test: the proxy unit test with a fake upstream.
4. `stt_api` must strip only a known platform prefix. `/files/...` without a prefix uses the default platform. Test: `test_routes.py`.
5. The weights script must be safe to run again: it skips a file that has the same size on the volume, and it never deletes on the volume.

---

## Facts checked for this plan (2026-11-23)

| Fact | Source |
|---|---|
| `runpod_network_volume`: `name`, `data_center` (change replaces), `size` (10 to 4096 GB, can grow, never shrink), `type` (`STANDARD` or `HIGH_PERFORMANCE`) | `terraform providers schema -json`, runpod 2.0 |
| `runpod_serverless_endpoint`: `network_volumes` (list), `data_center_ids` (list), `registry` (credential ID). `runpod_template.registry` too | Same |
| Data sources `runpod_registries`, `runpod_network_volumes`, `runpod_data_centers`, `runpod_gpu_types` exist | Same |
| A serverless worker mounts the network volume at `/runpod-volume`. 1 volume ties the workers to the data center of the volume | `docs.runpod.io/storage/network-volumes` |
| S3 API: endpoint `https://s3api-<dc lowercase>.runpod.io/`, region = data center ID (`EU-RO-1`), bucket = volume ID. Own S3 API keys (console, Settings, "S3 API keys"), not the Runpod API key. PutObject below 500 MB; multipart above (part at most 500 MB). No presigned URLs | `docs.runpod.io/serverless/storage/s3-api` |
| S3 API data centers: EU-CZ-1, EU-RO-1, EUR-IS-1, EUR-NO-1, US-CA-2, US-GA-2, US-IL-1, US-KS-2, US-MD-1, US-MO-1, US-MO-2, US-NC-1, US-NC-2, US-NE-1, US-WA-1 | Same |
| `infra/core` has no `runpod` provider yet. `scale-watch` reads every endpoint of the account, so it needs no change | `infra/core/*.tf` |
| The `gateway` module has no path parameters (`{id}`). STT-A paths need them | `infra/modules/gateway/main.tf` |
| The `model` facade passes no `extra_paths` to the gateway | `infra/modules/model/main.tf` |
| The CORS proxy lets only the gateway SA call it | `infra/modules/cors-proxy/main.tf` |

## Decisions in this plan (check them)

| Item | Choice | Why |
|---|---|---|
| Source of the volume copy | `gs://<project_id>-models/stt-a-qwen3-asr-diar/` (the folders that Vertex AI uses) | The same bytes on both platforms. No Hugging Face token on Runpod |
| Copy path | GCS JSON API read stream to S3 multipart upload, part by part (100 MB parts). Nothing on local disk | About 6 GB; the laptop disk and time stay small |
| Volume data center | `EU-RO-1` as the default in `main.tf`. The user confirms that it has `AMPERE_24` serverless GPUs before apply | It must have the S3 API and 24 GB GPUs. The agent cannot reach the Runpod API from the sandbox |
| Volume size | 20 GB, `STANDARD` | About 6 GB of weights plus room. It can grow later |
| GPU pools | `["AMPERE_24", "ADA_24"]` | More GPUs in 1 data center. All have 24 GB, as the L4 |
| `MODEL` on Runpod | `/runpod-volume/stt-a-qwen3-asr-diar` (`spec.weights.gcs_dir` under the mount) | The same folder layout as in GCS |
| `MODEL` on Vertex AI | Not set. `speech_engine` uses `AIP_STORAGE_URI` when `MODEL` is empty | No Vertex env reference syntax to rely on |
| Audio to the GPU | `stt_api` always sends a signed GET URL (15 minutes), on both platforms | 1 code path. `gs://` stays allowed for direct `/v1beta/interactions` calls on Vertex AI |
| `stt_api` to GPU | Through the CORS proxy with a Google ID token (audience = proxy URL). The `stt_api` SA gets `run.invoker` on the proxy | The provider keys stay in the proxy only (design) |
| Proxy cold wait | `COLD_WAIT = 280` s for a non-google target. A timeout before the response headers becomes 429 with `Retry-After: 30` | Below the 300 s gateway deadline |
| Registry name | `runpod_registry` named `gcp-models` in `infra/core`. The adapter finds its ID with the data source `runpod_registries` by name, in the child module `platform-runpod/registry/` (the mock provider cannot fill the nested list, so tests use `override_module`) | The deployment needs no `infra/core` state |
| `SETUP_PLATFORM` | Each adapter adds it. `speech_engine` adds `gpu` (`torch.cuda.get_device_name()`) to the setup record | Scores per platform and GPU (design) |

## File Structure

| File | Change |
|---|---|
| `deployments/stt-a-qwen3-asr-diar-vertex/` → `deployments/stt-a-qwen3-asr-diar/` | `git mv`. `backend.tf` keeps the workspace name |
| `deployments/stt-a-qwen3-asr-diar/main.tf` | `module "model"` = the facade. Delete `cors_proxy.tf` and `gateway.tf` |
| `deployments/stt-a-qwen3-asr-diar/moved.tf` | New: the `moved` blocks |
| `deployments/stt-a-qwen3-asr-diar/stt_api.tf`, `outputs.tf`, `alerts.tf`, `tests/*.tftest.hcl` | Facade outputs, proxy target, platform alerts |
| `deployments/stt-a-qwen3-asr-diar/services/speech_engine/speech_engine/{main,models,logic}.py`, `tests/` | Container contract |
| `deployments/stt-a-qwen3-asr-diar/services/stt_api/stt_api/{routes,files,gcp,server}.py`, `tests/` | Platform prefix, proxy call, signed audio URL |
| `infra/modules/platform-runpod/` | Own image, network volume, `MODEL`, `SETUP_PLATFORM` |
| `infra/modules/platform-vertex/main.tf` | `SETUP_PLATFORM = "vertex"` |
| `infra/modules/model/` | `extra_paths`, `proxy_invokers`, new outputs (`proxy_url`, `runpod_volume`) |
| `infra/modules/gateway/main.tf` | Path parameters from `{name}` in a path |
| `infra/modules/cors-proxy/` | `extra_invokers`, cold wait to 429, `PUT` not needed |
| `infra/core/runpod_registry.tf`, `versions.tf` / `main.tf` | Pull SA, key, `runpod_registry`, the `runpod` provider |
| `scripts/runpod-weights.py`, `scripts/tests/test_runpod_weights.py` | New |
| `scripts/hcp-sync.py`, `.env.example` | Working directory; `RUNPOD_S3_ACCESS_KEY`, `RUNPOD_S3_SECRET_KEY` |
| `README.md`, `infra/README.md`, `docs/README.md`, `CLAUDE.md`, `.claude/skills/model-ui/SKILL.md`, `ui/mock-server.mjs`, specs that name the folder | New folder name and the Runpod steps |

---

### Task 1: Rename the folder

- [ ] `git mv deployments/stt-a-qwen3-asr-diar-vertex deployments/stt-a-qwen3-asr-diar`.
- [ ] Replace the path in every file that names it (14 files today: `grep -rln stt-a-qwen3-asr-diar-vertex --exclude-dir=.terraform --exclude-dir=node_modules`). Keep the workspace name in `backend.tf` and the HCP key in `scripts/hcp-sync.py`; change only the working directory there. Keep the dated specs as they are, except for links that must still open.
- [ ] Remove the old `.terraform/` folder of the deployment and run `terraform init -backend=false` in the new one.
- [ ] Run `./scripts/check.py`. Expected: green, the same tests as before.

### Task 2: `speech_engine` container contract

- [ ] `main.py`: port from `PORT`, then `AIP_HTTP_PORT`, then 8080.
- [ ] `models.py`: model root from `MODEL`, else `AIP_STORAGE_URI`. A `gs://` value is copied to `/tmp/models` (as today). A local path is used as it is (Runpod volume, read only). Empty: `/tmp/models` (local run).
- [ ] `logic.py` `_audio`: accept `https://storage.googleapis.com/<AUDIO_BUCKET>/<name>?<query>` next to `gs://<AUDIO_BUCKET>/...`. Reject any other host or bucket, `http://`, an empty name, and `..` in the path. `models.py` reads an HTTPS URL with `urllib.request` (no credentials) and a `gs://` URI with the GCS client (Vertex AI only).
- [ ] `main.py` `SETUP`: add `platform` from `SETUP_PLATFORM` and `gpu` from the loaded models (`torch.cuda.get_device_name(0)`; empty in the unit tests).
- [ ] Tests first (`tests/test_logic.py`, `tests/test_main.py`): the allow-list cases, `MODEL` choice, the setup record keys. Run `python3 -m unittest discover -s tests -t .`.
- [ ] Image tag: next tag in `variables.tf` (`image_tag`). The user builds it with Cloud Build.

### Task 3: `stt_api` through the proxy

- [ ] `server.py`: env `TARGET` = the proxy URL, `PLATFORMS` = comma list (`vertex,runpod`), `DEFAULT` = first one.
- [ ] `routes.py` `route()`: strip a first path segment that is in `PLATFORMS`, and keep it as the platform of the call. Without a prefix: `DEFAULT`.
- [ ] `transcribe`: the GPU request gets `uri` = `signed_get(...)` of the audio (15 minutes), not `gs://`. Send `POST <TARGET>/<platform>/v1beta/interactions`.
- [ ] `gcp.py` `gpu_post`: Google ID token from the metadata server (`.../identity?audience=<TARGET>`), cached for 50 minutes. A 429 from the proxy comes back as it is (as today).
- [ ] The version record keeps the `setup` of the GPU answer, so `platform` and `gpu` come with it. `evaluation/` groups by the full setup, so it separates the platforms with no change. Check with a test.
- [ ] Tests first (`tests/test_routes.py`, `tests/test_gcp.py`): prefix strip, unknown first segment, the URL of the GPU call, the signed URL in the body.
- [ ] Next `stt_api_image_tag` in `variables.tf`.

### Task 4: CORS proxy cold wait and invokers

- [ ] `cors_proxy.py`: for a non-google target, open the upstream with `timeout = COLD_WAIT` (env, default 280). A `TimeoutError` before `getresponse()` returns becomes 429 with `Retry-After: 30` and a JSON body `{"error": "proxy: <platform> is starting"}`. After the headers arrive, the read timeout goes back to `TIMEOUT`.
- [ ] `main.tf` / `variables.tf`: `extra_invokers` (list of SA emails, default `[]`), 1 `run.invoker` member each. Use `count` on a list that is known at plan time, or one fixed member per input, as `gateway_invoker` does.
- [ ] Tests: a fake upstream that sleeps longer than `COLD_WAIT` (set 1 s in the test) gives 429. A fake upstream that answers at once and then sends a slow body gives 200 with the full body. Existing `cold_answer` tests stay.

### Task 5: Gateway path parameters and facade inputs

- [ ] `gateway/main.tf`: for each path, add `parameters = [{ name, in = "path", required = true, type = "string" }]` for every `{name}` in the path (`regexall("{([a-z_]+)}", path)`), on each operation and on `options`. No parameters: no key (the LLM-A document stays the same, so its API config does not change).
- [ ] `model/variables.tf`: `extra_paths` (same type as in `gateway`), `proxy_invokers` (list, default `[]`). Pass them to `gateway` and `cors_proxy`.
- [ ] `model/outputs.tf`: `proxy_url`, `runpod_volume` (`{ id, data_center }` or null).
- [ ] Tests: `gateway.tftest.hcl` asserts the parameters of `/v1beta/files/{id}` and of `/runpod/v1beta/files/{id}`. A test asserts that the LLM-A OpenAPI document has no `parameters` key.

### Task 6: Runpod adapter: own image and network volume

- [ ] Remove the precondition "stock images only". Own image: `image = "<region>-docker.pkg.dev/<project_id>/models/<spec.image.own>"`, `registry` = the ID of the `runpod_registries` entry named `options.registry` (default `gcp-models`). A missing entry fails at plan with a clear message ("apply infra/core first").
- [ ] `options.volume = { data_center, size_gb = 20, type = "STANDARD" }`: 1 `runpod_network_volume` (name = endpoint name). The endpoint gets `network_volumes = [id]` and `data_center_ids = [data_center]`. Env `MODEL = "/runpod-volume/<spec.weights.gcs_dir>"` and `HF_HUB_OFFLINE = "1"`.
- [ ] With a volume, `spec.weights.gcs_dir` is required and `revision` is not. Without a volume, the phase 3 rules stay (`hf_repo` and `revision`).
- [ ] Env `SETUP_PLATFORM = "runpod"`. `platform-vertex`: `SETUP_PLATFORM = "vertex"`.
- [ ] Output `volume` (`{ id, data_center }` or null).
- [ ] The endpoint does not replace when only the volume grows: the volume is not in `replace_triggered_by`.
- [ ] Tests (`platform-runpod/tests/`): own image URL and registry, volume and data center on the endpoint, `MODEL` env, `gcs_dir` required with a volume, LLM-A (stock image, no volume) unchanged.

### Task 7: `infra/core` registry key

- [ ] Add the `runpod` provider (`~> 2.0`) to `infra/core`. It reads `RUNPOD_API_KEY` (HCP already has it).
- [ ] `runpod_registry.tf`: SA `runpod-pull`, `roles/artifactregistry.reader` on the repo `models` only, a `google_service_account_key`, `runpod_registry` named `gcp-models` with `username = "_json_key"` and `password = base64decode(key.private_key)`.
- [ ] Test (`infra/core/tests/`): the reader role is on the `models` repo, not on the project.

### Task 8: STT-A into the facade

- [ ] `main.tf`: `module "model"` with `source = "../../infra/modules/model"`, `name = "stt-a-qwen3-asr-diar"`, `gateway_id = "stt-a-qwen3-asr-diar"`, `platforms = local.platforms` (`["vertex", "runpod"]`).
  - `spec.image = { own = "stt-a-qwen3-asr-diar:${var.image_tag}" }`, `args = []`, `env` = the current env (no `AUDIO_BUCKET` change), `health_route = "/health"`, `routes = ["/v1beta/interactions"]`, `gpu = "L4"`, `max_replicas = 1`, `weights = { hf_repo = "Qwen/Qwen3-ASR-1.7B", gcs_dir = local.model_dir }` (`hf_repo` is only a label here).
  - `platform_options.vertex`: `machine_type = "g2-standard-12"`, `shared_memory_size_mb = 16384`, `deployment_timeout = "1800s"`, `predict_route = "/v1beta/interactions"`.
  - `platform_options.runpod`: `gpu_pools = ["AMPERE_24", "ADA_24"]`, `volume = { data_center = "EU-RO-1" }`, `disk_gb = 60`.
  - `extra_paths`: every `/v1beta/uploads`, `/v1beta/files...` and `/v1beta/scores` path of today, with `module.stt_api.url`, the same methods and deadlines (30 s; 300 s for `transcribe` and `scores`).
  - `proxy_invokers = [module.stt_api.service_account_email]`.
- [ ] `moved.tf`: the blocks of the LLM-A `moved.tf` with the STT-A names. Check the real addresses with `terraform state list` (the user runs it, read only) and list them here before the user applies.
- [ ] `stt_api.tf`: `TARGET = module.model.proxy_url`, `PLATFORMS = join(",", local.platforms)`. Delete `local.raw_predict_url` and `google_project_iam_member.stt_api_predict` (the proxy calls Vertex AI now).
- [ ] `google_storage_bucket_iam_member.model_audio`: the member comes from the Vertex AI SA output of the facade. Keep it for direct `gs://` calls.
- [ ] `outputs.tf`: the LLM-A set (`platforms`, `targets`, `gateway_*`, `vertex`), plus `runpod_volume` for the weights script. `ui.platforms = module.model.ui_platforms`. `features.cold_start` moves into each platform entry (`retry-429` on both).
- [ ] `alerts.tf`: `scale_alerts` with `count` (Vertex AI), and `platform_alerts` for `module.model.scale_watch_ids`, as in LLM-A.
- [ ] Tests: update the 4 `tftest.hcl` files to the new addresses. New asserts: no `aiplatform.user` binding for the `stt_api` SA, the proxy invoker for the `stt_api` SA, the Runpod volume in `EU-RO-1`.

### Task 9: Weights script

- [ ] `scripts/runpod-weights.py deployments/<name>`: reads the outputs `runpod_volume` and `vertex` (the GCS weights folder) with `terraform output -json` (helper `tf()` as in the other scripts).
- [ ] Reads `RUNPOD_S3_ACCESS_KEY` and `RUNPOD_S3_SECRET_KEY` from `.env`. Never prints them.
- [ ] Lists `gs://<project_id>-models/<gcs_dir>/` (GCS JSON API, `gcloud auth print-access-token`), skips folder markers and `/.cache/`.
- [ ] For each object: `HEAD` on `s3://<volume_id>/<gcs_dir>/<name>`. Same size: skip. Else stream it: below 100 MB with 1 `PutObject`, else multipart with 100 MB parts. Abort the multipart upload on an error.
- [ ] AWS Signature V4 in the standard library (`hmac`, `hashlib`), region = data center ID, service `s3`, `UNSIGNED-PAYLOAD` is not assumed: sign the SHA-256 of each part.
- [ ] `--dry-run` lists what it would copy. At the end it prints the count and the bytes copied and skipped.
- [ ] Tests (`scripts/tests/test_runpod_weights.py`): the SigV4 signature against the AWS example vector, the part split, the skip rule. `check.py` finds the tests.
- [ ] `.env.example`: the 2 new lines, with a comment where to make the keys.

### Task 10: Docs

- [ ] Deployment README: the new folder name, the Runpod steps in order (below), the Runpod test call, the cold start row to measure, the S3 keys.
- [ ] `infra/README.md`: "Module: platform-runpod" (own images, `volume`), the `infra/core` registry, `scripts/runpod-weights.py` with placeholders.
- [ ] `docs/README.md`: the script list and the STT-A flow (stt_api → proxy → platform).
- [ ] `CLAUDE.md`: STT-A uses the facade; the new script.
- [ ] `.claude/skills/model-ui/SKILL.md`: STT-A has platforms.
- [ ] The multi-platform design spec: phase 6 row, "STT-A part done", the open points that this plan closed.
- [ ] `./scripts/check.py` green. `cd ui && npm test` green (`mock-server.mjs` path).

## What the user runs after this phase

1. In the Runpod console: make an S3 API key (Settings, "S3 API keys") and put it in `.env` as `RUNPOD_S3_ACCESS_KEY` and `RUNPOD_S3_SECRET_KEY`. Check that `EU-RO-1` has serverless `AMPERE_24` or `ADA_24` GPUs; if not, choose another S3 data center and change `main.tf`.
2. `./scripts/hcp-sync.py --dry-run`, then `./scripts/hcp-sync.py` (new working directory).
3. Apply `infra/core` (pull SA, key, `runpod_registry`).
4. Build the 2 images with Cloud Build (new tags).
5. Plan check: `terraform plan` in `deployments/stt-a-qwen3-asr-diar`. Expected: moves, a new API config, in-place updates of the gateway, the proxy and `stt_api`, new Runpod volume, template and endpoint. No replace of the Vertex AI endpoint, the gateway or a service account.
6. Apply. Then `./scripts/runpod-weights.py deployments/stt-a-qwen3-asr-diar --dry-run`, then without `--dry-run`.
7. `scripts/vertex.py undeploy`, then `scripts/vertex.py deploy deployments/stt-a-qwen3-asr-diar` (new image tag, project memory).
8. `./scripts/ui-deploy.py`.
9. Test calls through `/runpod/` and `/vertex/`. Record the Runpod cold start in the README.
