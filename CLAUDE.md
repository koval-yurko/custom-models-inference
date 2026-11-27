# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Terraform-only infrastructure for serving open-weight models (LLM, TTS, later STT) as private, scale-to-zero Cloud Run v2 services on GCP (`us-central1`). The only application code is the static test UI in `ui/` (React + Vite, see below). Research and design decisions are in `docs/research/` and `docs/specs/` (design + plan files, dated). Read the relevant spec before changing behaviour.

## Architecture

Two layers. Each Terraform root has its own HCP Terraform workspace (state), named in its `backend.tf`. Runs are remote (HCP Terraform executes plan and apply). Workspace variables, including the service account key as `GOOGLE_CREDENTIALS`, come from `.env` through `scripts/hcp-sync.py`; run it after every `.env` change. `.terraformignore` keeps secrets out of the config upload. All infra docs are in `infra/README.md`. Short guides with Mermaid diagrams are in `docs/README.md` (scripts, gateway and streaming, backends, keys and UI). Update them when you change a script, the gateway or the auth flow. For any diagram, use the project skill `diagrams` (Mermaid first, then D2, then draw.io, plus a render check in the Paseo browser).

1. `infra/core/` — one root, one apply, once per GCP project (workspace `custom-models-bootstrap`, the old name, kept for the state). Enables APIs, creates the `<project_id>-models` bucket, Artifact Registry repos (`models`, `ghcr` as a remote proxy for `ghcr.io` because Cloud Run cannot pull from `ghcr.io`, and `dockerhub` as a remote proxy for Docker Hub because Vertex AI pulls only from Artifact Registry), the budget, the `hf-token` secret, the `weights-copy` Cloud Run job (`weights_copy.tf`), the `scale-watch` Cloud Run job and its every-minute scheduler (`scale_watch.tf`: Slack messages for Runpod scale changes of LLM-A; the own images of STT-A and LLM-B post to Slack themselves on Runpod, from the Runpod secrets `slack_bot_token` and `slack_channel`), and in `gateways.tf` one API Gateway API per name in `local.gateway_apis` plus one shared API key restricted to those APIs.
   - `infra/modules/model-service/` — the shared module. One call = one private Cloud Run service + its service account + `run.invoker` for `invokers` + read-only GCS mount of the weights bucket at `/models`. Public invokers (`allUsers`, `allAuthenticatedUsers`) are rejected by validation. Min instances is always 0. The module sets `deletion_protection = false`.
   - `infra/modules/cors-proxy/` — private Cloud Run proxy in front of the platforms of a model (input `targets`; the first path segment picks the target). Vertex AI has no CORS, and API Gateway cannot add headers, so the proxy answers `OPTIONS` and adds CORS headers to every answer. The `model` module calls it (1 proxy per model).
   - `infra/modules/scale-alerts/` — 2 log-based alert policies for one model ("ready" after a cold start, "down" at scale down) to the Slack channel `models-slack` from `infra/core/notifications.tf`. Each deployment calls it in `alerts.tf`. See `infra/README.md` (section "Scale notifications (Slack)").
   - `infra/modules/model/` — the platform-neutral facade (design: `docs/specs/2026-11-22-multi-platform-design.md`). One call = 1 model spec on a list of platforms (LLM-A and LLM-B: `["vertex", "runpod"]`; STT-A: `["modal", "vertex", "runpod"]`): 1 adapter per platform (`platform-vertex` makes the Vertex AI service account, the objectViewer on the weights bucket and the dedicated private endpoint; `platform-runpod` makes a Runpod template and a load balancing endpoint that scales to 0, and for own images uses the `infra/core` registry credential `gcp-models` and an optional network volume for the weights, filled by `scripts/runpod-weights.py`; `platform-modal` makes no resource, because Modal has no Terraform provider: it gives the input of `scripts/platforms/modal.py`, which runs `modal deploy` with the shared app file `scripts/platforms/modal_app.py`, an accepted exception to the stdlib-only script rule), 1 CORS proxy with 1 target per platform (it reads the Runpod key from the secret `runpod-api-key` and the Modal proxy token from `modal-api-key`, and follows the 303 of a slow Modal answer), and 1 API Gateway (`infra/modules/gateway`) with the old paths plus `/<platform><route>`. Every GPU deployment uses it (STT-A adds `extra_paths` for its `stt_api` service). Post-apply: `scripts/deploy.py deploy|undeploy|status deployments/<name>` (the Vertex AI code is in `scripts/platforms/vertex.py`, the Modal code in `scripts/platforms/modal.py`). The Vertex AI model upload and deploy (scale to zero, Preview) run there after apply (it also fills the image cache of the proxy repo first), because the provider has no resource for them. See `infra/README.md` (section "Vertex AI (platform-vertex)") for routes, the HTTP 429 retry rule and the weights flow (`AIP_STORAGE_URI`). Own images follow the container contract of the spec: `PORT` and `MODEL` first, the `AIP_` values as fallback.
2. `deployments/<name>/` — one folder and one state per model (convention: never list several models in one root). Each calls the module with a pinned stock image plus flags/env. A deployment on the `model` module lists its platforms and its often-changed Runpod settings (`serve`, `data_centers`, `workers_max`, `flashboot`, GPUs) in `deploy.yaml`, which `main.tf` reads with `yamldecode` (see `infra/README.md`, "deploy.yaml"). Each deployment also has `alerts.tf`, which calls `infra/modules/scale-alerts/` for the Slack messages at scale up and scale down. `scripts/check.py` fails without it. A deployment can add a public API Gateway (`gateway.tf`: gateway SA, OpenAPI spec with `x-api-key`, API config, gateway) on the API that `infra/core/gateways.tf` creates with the same ID. Apply `infra/core/` first. Streaming on the gateway needs the post-apply script `scripts/gateway-streaming.py`, because the provider cannot set it.

Weights flow: Hugging Face → `weights-copy` job (GCS FUSE) → `<project_id>-models/<TARGET_DIR>/` → mounted at `/models` in the service, with `HF_HUB_OFFLINE=1`. `local.model_dir` in a deployment must match the job's `TARGET_DIR`.

## Commands

Terraform (remote runs on HCP) and `scripts/hcp-sync.py` are the tools (no Makefile, no CI).

```sh
terraform fmt -recursive                      # from repo root
cd infra/core && terraform init && terraform validate
./scripts/hcp-sync.py   # .env -> HCP workspaces (--dry-run first)
cd deployments/<name> && terraform init   # needs .env loaded (direnv): TF_CLOUD_ORGANIZATION and TF_TOKEN_app_terraform_io
cd deployments/<name> && terraform apply
```

Before every apply, run `./scripts/check.py` (fmt, validate, `terraform test` and `tflint` in every root; no credentials) and `./scripts/preflight.py` (read-only checks against the real project: stale shell, HCP region variable, APIs, bucket and repo region, Runpod balance, weights, L4 quota). Use the project skill `terraform-change-checklist`. tflint: install the binary from GitHub (Homebrew has no formula), then `tflint --init` once.

Tests use a mock provider and need no GCP credentials. Run from the directory that has the `tests/` folder:

```sh
cd infra/modules/model-service   # or infra/core, or deployments/tts-a-kokoro-cpu
terraform init -backend=false
terraform test                                   # all tests
terraform test -filter=tests/model_service.tftest.hcl   # one file
```

Test UI (`ui/`, design: `docs/specs/2026-11-11-test-ui-design.md`). Static React app in the public bucket `<project_id>-ui`, one tab per model. Tabs come from the `ui` Terraform output of each deployment through `scripts/ui-deploy.py` (writes `models.json`). A tab has a platform picker when its model has 2 or more deployed platforms (`ui_platforms` of the `model` module; hash `#/<tab>@<platform>`). To add or change a model in the UI, use the `model-ui` skill. Checks: `cd ui && npm install && npm test && npm run build`. Local: `npm run mock` plus `npm run dev` (see the skill).

Run the weights copy job: `gcloud run jobs execute weights-copy --wait --update-env-vars HF_REPO=<org/repo>,TARGET_DIR=<folder>`.

## Secrets and environment

All secrets live in the git-ignored root `.env` (template: `.env.example`). Never print or commit its values.

| Variable | Used by |
|---|---|
| `TF_CLOUD_ORGANIZATION`, `TF_CLOUD_PROJECT`, `TF_TOKEN_app_terraform_io` | Terraform: HCP Terraform state (the token replaces `terraform login`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the service account key JSON. `hcp-sync.py` uploads its content as the sensitive HCP variable `GOOGLE_CREDENTIALS` (used by remote runs). `.envrc` maps the path to `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE` for local gcloud |
| `GCP_PROJECT_ID`, `GCP_REGION`, `BILLING_ACCOUNT`, `INVOKER_EMAIL`, `BUDGET_AMOUNT` | `hcp-sync.py` writes them as HCP Terraform variables. `.envrc` also exports them as `TF_VAR_project_id`, `TF_VAR_region`, `TF_VAR_billing_account`, `TF_VAR_invoker_email`, `TF_VAR_budget_amount`. It also sets `CLOUDSDK_CORE_PROJECT` and `CLOUDSDK_RUN_REGION`, so gcloud commands need no `--project` or `--region` |
| `HF_TOKEN` | `.envrc` exports it as `TF_VAR_hf_token`; infra/core writes it to the `hf-token` secret (write-only, not in state) |
| `RUNPOD_API_KEY` | The `runpod` provider reads it (`hcp-sync.py` writes it to every HCP workspace as a sensitive env var). `.envrc` exports it as `TF_VAR_runpod_api_key`; infra/core writes it to the `runpod-api-key` secret (write-only), which the CORS proxies read |
| `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `MODAL_PROFILE` | `scripts/platforms/modal.py` runs the modal CLI with the token. `MODAL_PROFILE` is the Modal workspace name: `hcp-sync.py` writes it to the STT-A workspace as `modal_workspace` (the Modal web URL) |
| `MODAL_PROXY_TOKEN_ID`, `MODAL_PROXY_TOKEN_SECRET` | The Modal proxy token. `.envrc` and `hcp-sync.py` join them to `<id>.<secret>` (the Bearer form) as `TF_VAR_modal_api_key`; infra/core writes it to the `modal-api-key` secret (write-only), which the CORS proxies read |
| `SLACK_BOT_TOKEN`, `SLACK_CHANNEL` | `.envrc` exports them as `TF_VAR_slack_bot_token` and `TF_VAR_slack_channel`; infra/core makes the Slack channel `models-slack` (token write-only, not in state). `hcp-sync.py` also writes them to the Runpod secrets `slack_bot_token` and `slack_channel` (Runpod REST API). Quote the channel: `SLACK_CHANNEL="#models"` |

- `.envrc` (direnv) loads `.env` after a one-time `direnv allow`. It sets `CLOUDSDK_CONFIG=.gcloud/`, so gcloud never uses a global login or config.
- Every script in `scripts/` (and `.claude/skills/*/*.sh`) loads the repo `.env` itself. Run it directly, for example `./scripts/preflight.py --weights <folder> --l4`. Never put `direnv exec .` in front of a script, and never document it that way. A new script must load `.env` itself too (copy `load_env()` from `scripts/vertex.py`).
- Agent shells do not run the direnv hook. Only raw `terraform` and `gcloud` commands need it: run `direnv exec . terraform ...` and `direnv exec . gcloud ...`.
- `.worktreeinclude` lists the ignored files that Claude Code copies into new worktrees (`.env`, `.claude/settings.local.json`). In a new worktree, run `direnv allow` once: direnv approvals are per path. `.gcloud/` is not copied; gcloud makes it again from the key file. Keep the key file outside the repo: `.env` holds its absolute path, so every worktree finds it.
- The service account (`terraform@<project_id>.iam.gserviceaccount.com`) has `roles/owner` on the project. The billing-account role (Costs Manager) is not verified.

## Conventions and gotchas

- Scripts: write every helper script in Python 3 (standard library only), in `scripts/`. Do not write shell (`.sh`) scripts. Each script loads the repo `.env` itself and takes the deployment path as an argument (see `scripts/gateway-streaming.py`, `scripts/vertex.py`).
- Skills: create and update project skills only, in `.claude/skills/` of this repo. Do not create or change global skills in `~/.claude/skills/`, unless the user says so explicitly. Project skill for the run steps: `hcp-direnv-terraform`.
- There are no `terraform.tfvars` files (`*.tfvars` is git-ignored). All variable values come from `.env`. `.terraform.lock.hcl` is tracked on purpose; plans are not. Never commit tokens or keys.
- Every deployment sends Slack messages at scale up and scale down (`alerts.tf`, module `scale-alerts`). For a new deployment, follow `infra/README.md` (section "Add scale alerts to a new deployment"). Pick a `ready_text` that the server writes after the model is loaded, and check it in the real logs after the first cold start.
- Anti-goals from the specs: no public services, no min instances above 0, no model lists in one root.
- Billing budgets do not stop spend. GPU services bill per instance while running (L4 about $1/hour).
- The agent may run `terraform apply` and `terraform destroy` (`direnv exec . terraform ...`; `.claude/settings.json` allows them). Before an apply, it runs `./scripts/check.py` and a `terraform plan`, and reads the plan. It stops and asks when the plan replaces or destroys a resource that holds data or costs money to make again (endpoint with a deployed model, volume, bucket, gateway). It uses only the apply and destroy steps of the deployment README, so the user can run the same steps by hand. When a step is missing or wrong in the README, the agent fixes the README first.
- Never run `terraform destroy -target` on a part of a model (a Runpod volume or endpoint). Terraform also destroys every resource that depends on it: on 2026-11-27 this removed the LLM-B proxy and gateway. To take a platform out of service, set `serve: false` in `deploy.yaml`. To remove it, delete its entry. Then run a normal plan and apply.
- Per-deployment READMEs hold the apply, test-call (`gcloud auth print-identity-token`), cold-start and scale-to-zero checks.
- Where docs go: the root `README.md` has the overview, the global setup and links. It has no step that belongs to one model. `infra/README.md` has the shared parts (core, modules) and uses placeholders such as `HF_REPO=<org/repo>`. The README of a deployment has every command for that model, with real values: preflight flags, weights copy, apply, deploy, gateway streaming, test, destroy. Link to a section. Do not repeat the same command in two files.
- Global or specific: `check.py` and the base `preflight.py` are global. The flags `--weights <folder>` and `--l4` belong to the deployment README.
- Real-GCP commands (apply, destroy, deploy, test calls) run only when the user or the current card asks for them. A test call on a GPU costs money: say the price first. Never print the real API key or any `.env` value.
- UI test with Claude in Chrome (only when the user asks): open the UI URL, copy the key silently with `cd infra/core && direnv exec . terraform output -raw api_key | pbcopy`, paste it with cmd+v into the key field, then clear the clipboard with `printf '' | pbcopy`. Before the test, compare the gateway URLs in the deployed `models.json` (`curl` the UI bucket) with the real gateways. A LLM call starts a GPU replica (about $1.34 per hour), so say so first. After a key paste, click "Reload voices" on the TTS tab.
- After a gateway recreate, run `scripts/gateway-streaming.py <deployment>` and then `scripts/ui-deploy.py`. The URL can change. Google tokens last 1 hour, so a long operation needs a token refresh (`vertex.py` does it).
- An empty HCP workspace left after a deployment removal is deleted by the user in the HCP UI. Tell the user its name.
- Docs prose in this repo is written in Simplified Technical English (short sentences, active voice, no contractions). Match that style.

## Recommended tools for working here

Already installed: `terraform`, `gcloud`. Useful MCP servers and skills:

- `context7` MCP — current docs for the `google` provider and vLLM flags (versions move fast; the provider is pinned `~> 8.10`).
- `pycharm` MCP (in `.mcp.json`) — file and symbol search; optional, the repo has no Python.
- `superpowers` plugin (enabled in `.claude/settings.json`) — brainstorming, writing-plans and verification skills match the spec/plan workflow in `docs/specs/`.
- Optional: a Terraform MCP server (`hashicorp/terraform-mcp-server`) for provider and module lookups, and `tflint` for linting (installed, see Commands).
