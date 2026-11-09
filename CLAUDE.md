# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Terraform-only infrastructure for serving open-weight models (LLM, TTS, later STT) as private, scale-to-zero Cloud Run v2 services on GCP (`europe-west4`). There is no application code. Research and design decisions are in `docs/research/` and `docs/specs/` (design + plan files, dated). Read the relevant spec before changing behaviour.

## Architecture

Three layers. Each Terraform root has its own HCP Terraform workspace (state), named in its `backend.tf`. Runs are remote (HCP Terraform executes plan and apply). Workspace variables, including the service account key as `GOOGLE_CREDENTIALS`, come from `.env` through `scripts/hcp-sync.py`; run it after every `.env` change. `.terraformignore` keeps secrets out of the config upload.

1. `infra/bootstrap/` — applied once per GCP project. Enables APIs, creates the `<project_id>-models` bucket, Artifact Registry repos (`models`, and `ghcr` as a remote proxy for `ghcr.io` because Cloud Run cannot pull from `ghcr.io`), the budget, the `hf-token` secret, and the `weights-copy` Cloud Run job.
2. `infra/modules/model-service/` — the shared module. One call = one private Cloud Run service + its service account + `run.invoker` for `invokers` + read-only GCS mount of the weights bucket at `/models`. Public invokers (`allUsers`, `allAuthenticatedUsers`) are rejected by validation. Min instances is always 0. The module sets `deletion_protection = false`.
3. `deployments/<name>/` — one folder and one state per model (convention: never list several models in one root). Each calls the module with a pinned stock image plus flags/env. 

Weights flow: Hugging Face → `weights-copy` job (GCS FUSE) → `<project_id>-models/<TARGET_DIR>/` → mounted at `/models` in the service, with `HF_HUB_OFFLINE=1`. `local.model_dir` in a deployment must match the job's `TARGET_DIR`.

## Commands

Terraform (remote runs on HCP) and `scripts/hcp-sync.py` are the tools (no tflint, no Makefile, no CI).

```sh
terraform fmt -recursive                      # from repo root
cd infra/bootstrap && terraform init && terraform validate
./scripts/hcp-sync.py   # .env -> HCP workspaces (--dry-run first)
cd deployments/<name> && terraform init   # needs .env loaded (direnv): TF_CLOUD_ORGANIZATION and TF_TOKEN_app_terraform_io
cd deployments/<name> && terraform apply
```

Tests use a mock provider and need no GCP credentials. Run from the directory that has the `tests/` folder:

```sh
cd infra/modules/model-service   # or infra/bootstrap
terraform init -backend=false
terraform test                                   # all tests
terraform test -filter=tests/model_service.tftest.hcl   # one file
```

Run the weights copy job: `gcloud run jobs execute weights-copy --wait --update-env-vars HF_REPO=<org/repo>,TARGET_DIR=<folder>`.

## Secrets and environment

All secrets live in the git-ignored root `.env` (template: `.env.example`). Never print or commit its values.

| Variable | Used by |
|---|---|
| `TF_CLOUD_ORGANIZATION`, `TF_CLOUD_PROJECT`, `TF_TOKEN_app_terraform_io` | Terraform: HCP Terraform state (the token replaces `terraform login`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the service account key JSON. `hcp-sync.py` uploads its content as the sensitive HCP variable `GOOGLE_CREDENTIALS` (used by remote runs). `.envrc` maps the path to `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE` for local gcloud |
| `GCP_PROJECT_ID`, `GCP_REGION`, `BILLING_ACCOUNT`, `INVOKER_EMAIL`, `BUDGET_AMOUNT` | `hcp-sync.py` writes them as HCP Terraform variables. `.envrc` also exports them as `TF_VAR_project_id`, `TF_VAR_region`, `TF_VAR_billing_account`, `TF_VAR_invoker_email`, `TF_VAR_budget_amount`. It also sets `CLOUDSDK_CORE_PROJECT` and `CLOUDSDK_RUN_REGION`, so gcloud commands need no `--project` or `--region` |
| `HF_TOKEN` | `.envrc` exports it as `TF_VAR_hf_token`; bootstrap writes it to the `hf-token` secret (write-only, not in state) |

- `.envrc` (direnv) loads `.env` after a one-time `direnv allow`. It sets `CLOUDSDK_CONFIG=.gcloud/`, so gcloud never uses a global login or config.
- Agent shells do not run the direnv hook. Run `direnv exec . terraform ...` and `direnv exec . gcloud ...`.
- `.worktreeinclude` lists the ignored files that Claude Code copies into new worktrees (`.env`, `.claude/settings.local.json`). In a new worktree, run `direnv allow` once: direnv approvals are per path. `.gcloud/` is not copied; gcloud makes it again from the key file. Keep the key file outside the repo: `.env` holds its absolute path, so every worktree finds it.
- The service account (`terraform@<project_id>.iam.gserviceaccount.com`) has `roles/owner` on the project. The billing-account role (Costs Manager) is not verified.

## Conventions and gotchas

- There are no `terraform.tfvars` files (`*.tfvars` is git-ignored). All variable values come from `.env`. `.terraform.lock.hcl` is tracked on purpose; plans are not. Never commit tokens or keys.
- Anti-goals from the specs: no public services, no min instances above 0, no model lists in one root.
- Billing budgets do not stop spend. GPU services bill per instance while running (L4 about $1/hour).
- Apply, test calls and destroy against real GCP are run by the user, not by the agent. The agent verifies with `terraform fmt`, `validate` and `terraform test`.
- Per-deployment READMEs hold the apply, test-call (`gcloud auth print-identity-token`), cold-start and scale-to-zero checks.
- Docs prose in this repo is written in Simplified Technical English (short sentences, active voice, no contractions). Match that style.

## Recommended tools for working here

Already installed: `terraform`, `gcloud`. Useful MCP servers and skills:

- `context7` MCP — current docs for the `google` provider and vLLM flags (versions move fast; the provider is pinned `~> 8.10`).
- `pycharm` MCP (in `.mcp.json`) — file and symbol search; optional, the repo has no Python.
- `superpowers` plugin (enabled in `.claude/settings.json`) — brainstorming, writing-plans and verification skills match the spec/plan workflow in `docs/specs/`.
- Optional: a Terraform MCP server (`hashicorp/terraform-mcp-server`) for provider and module lookups, and `tflint` for linting (not installed).
