# GCP bootstrap, model-service module, TTS-A Kokoro (CPU): Implementation Plan

> Update: Terraform state now lives in HCP Terraform workspaces, not GCS. The `<project_id>-tfstate` bucket and `backend "gcs"` blocks below are replaced by `cloud {}` blocks. See `infra/bootstrap/README.md`.
> Update: variable values now come from `.env` as `TF_VAR_*` (see `.envrc`). The `terraform.tfvars` files described below do not exist.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Terraform code for a one-time GCP bootstrap, a shared Cloud Run v2 module, and the first deployment (Kokoro-82M on CPU), ready for the user to apply.

**Architecture:** 3 independent Terraform units. `infra/bootstrap/` is a root with local state first. `infra/modules/model-service/` is a module with `terraform test` unit tests on a mock provider. `deployments/tts-a-kokoro-cpu/` is a root with a GCS backend that calls the module.

**Tech Stack:** Terraform 1.14, `hashicorp/google` provider (current major; check it on the Terraform Registry), `terraform test` with `mock_provider`.

**Spec:** `docs/specs/2026-11-09-bootstrap-model-service-tts-a-design.md`

## Global Constraints

- Region default: `europe-west4`. Every bucket, repo and service uses `var.region`.
- Budget default: `20` USD, thresholds `0.5`, `0.9`, `1.0`, default recipients.
- Terraform does not create the GCP project.
- Never grant `roles/run.invoker` to `allUsers` or `allAuthenticatedUsers`.
- `min_instance_count = 0` on every service. Module default `max_instances = 1`.
- `deletion_protection = false` on the Cloud Run service.
- Kokoro image tag: `v0.10.0`, pulled through the Artifact Registry remote repo `ghcr`.
- TTS-A resources: `cpu = "4"`, `memory = "8Gi"`, no GPU, no weights bucket, probe path `/health`.
- State prefixes: `infra/bootstrap`, `deployments/tts-a-kokoro-cpu`.
- Track `terraform.tfvars` and `.terraform.lock.hcl` in git (see `.gitignore`). No secrets in tfvars.
- Before you use an argument name, check it against the current `hashicorp/google` docs (context7 or the Registry).
- This card ends with code only. The agent runs `fmt`, `validate` and `test`. The agent does not run `apply`.

## Review Focus

1. A member string `allUsers` or `allAuthenticatedUsers` in `invokers` must fail at plan time with a clear error. Test: `rejects_public_invoker` in Task 1.
2. A long `name` (for example 40 characters) must still give a valid service account ID (6 to 30 characters, `[a-z][a-z0-9-]*[a-z0-9]`). Test: `long_name_gives_valid_sa_id` in Task 1.
3. A GPU set with too little CPU or memory (L4 needs at least 4 CPU and 16 GiB) fails only at apply time on GCP. The module documents the minimums in the `gpu_type` description. There is no test, because GCP owns the rule.
4. The first bootstrap apply in a new project must not fail because an API is not enabled yet. Every dependent resource has `depends_on = [google_project_service.apis]`. Check this in the review of Task 2.
5. `terraform destroy` of TTS-A must not fail on deletion protection. Test: `cpu_only_defaults` in Task 1 asserts `deletion_protection == false`.

---

### Task 1: Module `model-service` with unit tests

**Files:**
- Create: `infra/modules/model-service/versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`, `README.md`
- Test: `infra/modules/model-service/tests/model_service.tftest.hcl`

**Interfaces:**
- Consumes: nothing.
- Produces: the module inputs from the spec table (`project_id`, `region`, `name`, `image`, `args`, `env`, `port`, `cpu`, `memory`, `gpu_type`, `concurrency`, `max_instances`, `timeout`, `startup_probe_path`, `startup_failure_threshold`, `weights_bucket`, `invokers`) and the outputs `url`, `service_name`, `service_account_email`.

- [ ] **Step 1: Write the failing tests** in `tests/model_service.tftest.hcl`. Use `mock_provider "google" {}` and `command = plan` in every run. Base variables: `project_id = "p"`, `region = "europe-west4"`, `name = "tts-a-kokoro-cpu"`, `image = "img"`, `invokers = ["user:a@b.c"]`.
  - `cpu_only_defaults`: assert `scaling[0].min_instance_count == 0`, `max_instance_count == 1`, `deletion_protection == false`, no `node_selector`, no `volumes`, `cpu_idle == true`, and no `google_storage_bucket_iam_member`.
  - `gpu_service`: `gpu_type = "nvidia-l4"`. Assert `node_selector[0].accelerator == "nvidia-l4"`, the limit `nvidia.com/gpu == "1"`, `gpu_zonal_redundancy_disabled == true`, `cpu_idle == false`.
  - `weights_volume`: `weights_bucket = "w"`. Assert 1 volume with `gcs[0].bucket == "w"` and `read_only == true`, mount path `/models`, and 1 bucket IAM member with role `roles/storage.objectViewer`.
  - `http_probe`: `startup_probe_path = "/health"`. Assert `startup_probe[0].http_get[0].path == "/health"`. With the default `null`, assert a `tcp_socket` probe.
  - `invokers_bound`: 2 invokers. Assert 2 `google_cloud_run_v2_service_iam_member` items, all with role `roles/run.invoker`.
  - `rejects_public_invoker`: `invokers = ["allUsers"]`, then `expect_failures = [var.invokers]`. Repeat with `allAuthenticatedUsers`.
  - `long_name_gives_valid_sa_id`: `name = "tts-b-qwen3-tts-1p7b-vllm-omni-service"`. Assert `length(google_service_account.this.account_id) <= 30` and that it matches `^[a-z][a-z0-9-]{4,28}[a-z0-9]$`.

- [ ] **Step 2: Run the tests to make sure they fail**

Run: `terraform -chdir=infra/modules/model-service init -backend=false && terraform -chdir=infra/modules/model-service test`
Expected: FAIL (no resources defined).

- [ ] **Step 3: Implement the module.** `versions.tf`: `required_version >= 1.7`, google provider constraint. `variables.tf`: the spec table, with a `validation` block on `invokers` that rejects `allUsers` and `allAuthenticatedUsers`. `main.tf`: resources `google_service_account.this`, `google_cloud_run_v2_service.this`, `google_cloud_run_v2_service_iam_member.invoker` (`for_each = toset(var.invokers)`), `google_storage_bucket_iam_member.weights` (`count` on `weights_bucket != null`). Use `dynamic` blocks for `node_selector`, `volumes`, `volume_mounts`, `http_get` and `tcp_socket`. SA account ID: the name when it is 30 chars or less, else the first 25 chars + "-" + 4 sha256 hex chars.

- [ ] **Step 4: Run the tests to make sure they pass**

Run: `terraform -chdir=infra/modules/model-service test && terraform fmt -check -recursive infra/modules`
Expected: all runs pass, `fmt` prints nothing.

- [ ] **Step 5: Write `README.md`** with the input table, the outputs, the GPU minimums (L4: 4 CPU and 16 GiB; RTX PRO 6000: 20 CPU and 80 GiB) and one usage example.

- [ ] **Step 6: Commit**

```bash
git add infra/modules/model-service
git commit -m "feat: add model-service Cloud Run module with unit tests"
```

### Task 2: Bootstrap root

**Files:**
- Create: `infra/bootstrap/versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`, `terraform.tfvars`, `backend.tf.example`, `README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: bucket `<project_id>-tfstate` (used by Task 3 through `-backend-config`), remote repo `ghcr` (Task 3 image prefix `<region>-docker.pkg.dev/<project_id>/ghcr`). Outputs `state_bucket`, `weights_bucket`, `models_repo`, `ghcr_repo`, `region`.

- [ ] **Step 1: Write the provider and variables.** Provider `google` with `project`, `region`, `user_project_override = true`, `billing_project = var.project_id`. Variables `project_id`, `billing_account`, `region = "europe-west4"`, `budget_amount = 20`.

- [ ] **Step 2: Write the resources** from spec section "infra/bootstrap/": `google_project_service.apis` (`for_each` on the 8 APIs, `disable_on_destroy = false`), the 2 buckets, repo `models` (`format = "DOCKER"`, standard), repo `ghcr` (`mode = "REMOTE_REPOSITORY"`, Docker custom upstream `https://ghcr.io`), `data.google_project.this`, and `google_billing_budget` filtered on `projects/${data.google_project.this.number}`. Each resource that uses an API has `depends_on = [google_project_service.apis]`.

- [ ] **Step 3: Write `terraform.tfvars`** with placeholders `project_id = "REPLACE_ME"` and `billing_account = "REPLACE_ME"`, and `backend.tf.example` with the GCS backend block (`prefix = "infra/bootstrap"`).

- [ ] **Step 4: Validate**

Run: `terraform -chdir=infra/bootstrap init -backend=false && terraform -chdir=infra/bootstrap validate && terraform fmt -check infra/bootstrap`
Expected: `Success! The configuration is valid.` and no `fmt` output.

- [ ] **Step 5: Write `README.md`**: the prerequisites from the spec, then `init`, `apply`, copy `backend.tf.example` to `backend.tf`, and `terraform init -migrate-state`.

- [ ] **Step 6: Commit**

```bash
git add infra/bootstrap
git commit -m "feat: add GCP bootstrap (APIs, buckets, registries, budget)"
```

### Task 3: Deployment `tts-a-kokoro-cpu`

**Files:**
- Create: `deployments/tts-a-kokoro-cpu/main.tf`, `backend.tf`, `variables.tf`, `outputs.tf`, `terraform.tfvars`, `README.md`

**Interfaces:**
- Consumes: Task 1 module (`source = "../../infra/modules/model-service"`), Task 2 bucket and `ghcr` repo.
- Produces: output `url`.

- [ ] **Step 1: Write the files** as in spec section "deployments/tts-a-kokoro-cpu/". `backend.tf` has `backend "gcs" { prefix = "deployments/tts-a-kokoro-cpu" }` and no bucket. Variables `project_id`, `region = "europe-west4"`, `invoker_email`. `terraform.tfvars` holds placeholders.

- [ ] **Step 2: Validate**

Run: `terraform -chdir=deployments/tts-a-kokoro-cpu init -backend=false && terraform -chdir=deployments/tts-a-kokoro-cpu validate && terraform fmt -check deployments`
Expected: `Success! The configuration is valid.` and no `fmt` output.

- [ ] **Step 3: Check the voice name.** Read `api/src/voices` (or the voices list) in the `remsky/Kokoro-FastAPI` repo at tag `v0.10.0` with `gh api`. Confirm `af_heart`, or use a voice that exists.

- [ ] **Step 4: Write `README.md`** with the 4 user steps from the spec (apply, curl test, scale to zero check, destroy and list).

- [ ] **Step 5: Commit**

```bash
git add deployments/tts-a-kokoro-cpu
git commit -m "feat: add tts-a Kokoro CPU deployment"
```

### Task 4: Final check across the repo

- [ ] **Step 1: Run all checks**

Run: `terraform fmt -check -recursive && terraform -chdir=infra/modules/model-service test && terraform -chdir=infra/bootstrap validate && terraform -chdir=deployments/tts-a-kokoro-cpu validate`
Expected: all pass.

- [ ] **Step 2: Grep for public access**

Run: `grep -rn "allUsers\|allAuthenticatedUsers" infra deployments`
Expected: only the validation block in `infra/modules/model-service/variables.tf` and its test.

- [ ] **Step 3: Commit the lock files** if `init` created or changed them.
