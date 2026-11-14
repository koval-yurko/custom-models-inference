---
name: hcp-direnv-terraform
description: Run Terraform on HCP Terraform with direnv-loaded .env, gcloud isolated by CLOUDSDK_CONFIG, and workspaces synced by scripts/hcp-sync.py. Use when the user applies or plans a Terraform root in a repo with .envrc and hcp-sync.py (for example custom-models), or sees "organization must be set", "Unreadable module directory", or asks which gcloud identity is used.
---

# HCP Terraform with direnv

## Steps (user terminal, direnv hook active)

1. In the repo root, run `direnv allow` once. Run it again after `.envrc` changes.
2. In the repo root, run `./scripts/hcp-sync.py --dry-run`, then `./scripts/hcp-sync.py`. Run it again after each `.env` change.
3. `cd deployments/<name>`.
4. Run `terraform init`, then `terraform plan` or `terraform apply`. No `direnv exec .` prefix.

## Agent shells

An agent shell has no direnv hook, and shell state does not persist between commands. Prefix each command: `direnv exec . terraform plan`, `direnv exec . gcloud ...`. `direnv exec` finds `.envrc` in a parent folder. The agent does not run apply, destroy or real GCP calls unless the repo says so. Read the repo `CLAUDE.md` first.

## Facts

- `.envrc` sets `CLOUDSDK_CONFIG=.gcloud/` and maps `GOOGLE_APPLICATION_CREDENTIALS` to `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE`. gcloud uses the service account, not the global login. Check with `gcloud auth list`.
- Runs are remote. HCP uses the workspace variables, not the local `.env`. A `.env` change has no effect until `hcp-sync.py` runs.
- A deployment that uses a module outside its folder (`../../infra/modules/...`) needs the workspace working directory `deployments/<name>`. `hcp-sync.py` sets it. Add each new workspace to the `WORKSPACES` map in `scripts/hcp-sync.py`.

## Errors

| Error | Cause and fix |
|---|---|
| `"organization" must be set` | direnv is blocked or not loaded. Run `direnv allow`. Check `echo $TF_CLOUD_ORGANIZATION`. |
| `Unreadable module directory ... ../../infra` | The workspace has no working directory. Run `./scripts/hcp-sync.py` in the repo root. |
| Warning `Provider development overrides are in effect` | From the local CLI config. It does not affect the remote run. |
