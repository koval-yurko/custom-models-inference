---
name: verify-gcp
description: Verify the Terraform code and the real GCP project of this repo (Cloud Run, Vertex AI, API Gateway, the UI bucket) in 4 levels, from free and offline to paid model calls. Use after a .tf change, after an apply, a Vertex AI deploy, gateway-streaming.py or ui-deploy.py, when the UI or a gateway call fails, or when the user asks "is it deployed right". Use verify-ui for the browser UI.
---

# Verify Terraform and GCP

Run the levels in order. Stop at the first FAIL and fix it. Each level is faster or cheaper than the next one.

| Level | Command | Time | Cost | Needs |
|---|---|---|---|---|
| 1. Code | `./scripts/check.py` | about 2 min | free | nothing (mock provider) |
| 2. State | `./scripts/verify-gcp.py state` | about 10 s | free, read-only | `.env` |
| 2b. Drift | `./scripts/verify-gcp.py state --plan` | about 5 min | free, read-only | `.env`, HCP access |
| 3. Smoke (curl) | `./scripts/verify-gcp.py smoke` | about 3 s warm, up to 5 min cold | free (can wake a CPU service) | network |
| 4. Calls | `./scripts/verify-gcp.py call --tts` / `--llm` | 10 s (TTS), up to 15 min (LLM cold) | TTS: cents. LLM: L4 GPU, about $0.40 per check | `.env`, HCP access, user consent |

Warning: run level 4 only when the user asks for it in the same message (`CLAUDE.md`). Say the cost first. Apply, destroy and deploy are never part of this skill.

All scripts load the repo `.env` themselves, so no `direnv exec` is needed. Each `verify-gcp.py` run writes its output to `.verify/gcp/<run-id>-<level>/report.txt` (git-ignored). A run exits 1 on a FAIL. A WARN means "look at it": the check could not decide, or something is slow.

## 1. Code: `check.py`

`fmt`, `validate`, `terraform test` (mock provider) and `tflint` in every root. It finds config errors only. For the steps around an apply, use the `terraform-change-checklist` skill.

## 2. State: `verify-gcp.py state`

Read-only `gcloud` calls. It checks the anti-goals of the specs on the real project, not on the code:

- Cloud Run (`GCP_REGION`): every service has min instances `0` and no `allUsers` or `allAuthenticatedUsers` member.
- Vertex AI: every deployed model has min replicas `0`. An endpoint with no deployed model is a WARN (run `scripts/vertex.py deploy`).
- API Gateway: every gateway is `ACTIVE`.
- Test UI: every tab in the deployed `models.json` (UI bucket) points to a live gateway. A gateway with no tab is a WARN. Fix a stale URL with `./scripts/ui-deploy.py --config-only`.

`--plan` also runs `terraform plan -detailed-exitcode -lock=false` in `infra/core` and every deployment. It runs on HCP, so it is slow. Each root must print `No changes`. A FAIL shows the plan summary. Run `terraform plan` in that root to see the resource, then tell the user. Do not apply.

## 3. Smoke: `verify-gcp.py smoke`

The fast path. It uses plain HTTP, as `curl` does, with no API key, so no model runs:

- The UI page (`index.html`, title `Model tests`) and `models.json` load. `models.json` has `Cache-Control: no-cache`.
- For each tab and each route of its type (`llm`: `POST /v1/chat/completions`; `tts`: `POST /v1/audio/speech`, `GET /v1/audio/voices`):
  - a call with no key gets `401` or `403` from the gateway (the backend is not reached);
  - the CORS preflight (`OPTIONS` with `Origin: https://storage.googleapis.com`) gets `2xx`, `Access-Control-Allow-Origin` `*` and `x-api-key` in `Access-Control-Allow-Headers`.

The LLM preflight is answered by the CORS proxy (`infra/modules/cors-proxy`), never by Vertex AI, so it does not start the GPU. The TTS preflight reaches Kokoro on Cloud Run CPU. When Kokoro is at 0 instances, the first preflight waits for its cold start (more than 60 s was measured; the gateway allows 300 s). The check reports that as a WARN with the time, not a FAIL.

The same checks by hand, for one gateway (`GW` from the `ui` output or `models.json`):

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$GW/v1/chat/completions"     # 401: the gateway wants the key
curl -si -X OPTIONS "$GW/v1/chat/completions" -H "Origin: https://storage.googleapis.com" \
  -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: content-type,x-api-key" | grep -i '^access-control'
curl -s "https://storage.googleapis.com/$GCP_PROJECT_ID-ui/models.json"         # the tabs the UI shows
```

What curl cannot verify: the UI logic (React state, streaming playback, the 429 retry loop, error texts). For that, use the `verify-ui` skill (browser, local mock).

## 4. Calls: `verify-gcp.py call --tts | --llm`

Real calls with the shared API key. The key comes from `terraform output -raw api_key` in `infra/core` and is never printed.

- `--tts`: `GET /v1/audio/voices` must be `200`, and one short `POST /v1/audio/speech` (`wav`) must return a file that starts with `RIFF`.
- `--llm`: one chat call (`max_tokens` 32). At 0 replicas, Vertex AI answers `429`: the script retries every 30 s, at most 60 times (the same rule as the UI). It must end with `200` and a non-empty answer. After the check, the replica stays up for about 15 minutes. Check scale to zero later with the `cloud-run-instances` skill (Cloud Run) or the Vertex AI console (see the deployment README).

## Evidence

- Keep the `report.txt` of every level you ran. Name the run ID in your report.
- A pass at level 3 proves the gateways, the auth and the CORS setup. It does not prove that a model answers. Say which levels ran.

## Cleanup

Levels 1 to 3 leave nothing behind, except a CPU instance that a preflight can wake: it stops by itself after about 15 minutes. After level 4 with `--llm`, tell the user that the GPU replica bills until it scales to zero. Old report folders stay in `.verify/gcp/`. Delete them when the user no longer needs them.

## Gotchas

- `verify-gcp.py` does not check the Slack alerts. After a cold start, check the log line of the alert (`infra/README.md`, "Add scale alerts to a new deployment", step 8), or ask the user if the Slack message came.
- The gateways run in `gateway_region` (default `europe-west1` in each deployment's `variables.tf`), and the services run in `GCP_REGION`. So the gateway host names end with `europe-west1.gateway.dev`. This is expected, not drift.
- A drift in `google_billing_budget.monthly` means `BUDGET_AMOUNT` in `.env` and the real budget differ. Either `hcp-sync.py` plus an apply of `infra/core` is pending, or someone changed the budget in the console. Ask the user which value is right.
- `state --plan` runs `terraform init` in each root (it connects the root to its HCP workspace). That is read-only, but it writes `.terraform/` in the root.
- The billing role of the service account is not verified (`CLAUDE.md`), so this skill does not check the budget itself.
