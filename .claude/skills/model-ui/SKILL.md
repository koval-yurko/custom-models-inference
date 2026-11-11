---
name: model-ui
description: Add or update a model in the test UI (ui/, React, one tab per model). Use when a new deployment gets an API Gateway, when a deployment changes its routes, model name or features (streaming, voices, formats), when a new model type (for example STT) needs a panel, or after an apply or gateway-streaming.py run changed a gateway URL.
---

# Model test UI: add or update a model

The test UI is a static React app in `ui/`. It is served from the public bucket `<project_id>-ui` (`infra/core/ui.tf`). It has no backend: the browser calls the API Gateway of each model with the shared `x-api-key`. Read `infra/README.md`, section "Test UI", first.

How the UI knows the models:

```
deployments/<name>/outputs.tf  output "ui" {...}     (each model owns its UI entry)
        -> terraform output -json ui                  (needs an apply: a new output is in the state only after apply)
        -> scripts/ui-deploy.py -> models.json        (uploaded next to index.html, no cache)
        -> ui/src/App.tsx: 1 tab per entry, panel = ui/src/panels/index.ts[type]
```

Never hard-code a gateway URL in `ui/`. The URL changes when the gateway is replaced.

## The `ui` output

```hcl
# The test UI reads this output (scripts/ui-deploy.py -> models.json). Schema: .claude/skills/model-ui/SKILL.md.
output "ui" {
  description = "Tab of this model in the test UI."
  value = {
    id       = local.gateway_id                                            # unique, used in the URL: #/<id>
    title    = "STT-A Qwen3 ASR"                                           # tab name
    type     = "stt"                                                       # key in ui/src/panels/index.ts
    base_url = "https://${google_api_gateway_gateway.this.default_hostname}"
    model    = "qwen3-asr"                                                 # the "model" field of the request
    features = { stream = true }                                           # read by the panel (see below)
  }
}
```

`features` by type (the panel reads only these keys; add a key when you add a feature):

| type | key | meaning |
|---|---|---|
| all | `cold_start = "vertex-429"` | Vertex AI returns 429 at 0 replicas. The UI retries every 30 s, at most 60 times. Set it for every Vertex AI deployment. |
| `tts` | `stream` | Gateway streaming is on (`scripts/gateway-streaming.py`). Enables "Stream and play at once" (PCM). |
| `tts` | `voices`, `default_voice` | `GET /v1/audio/voices` exists and returns `{"voices": [...]}`. |
| `tts` | `formats`, `sample_rate` | `response_format` values; sample rate of `pcm` (16-bit mono). |
| `llm` | `stream`, `max_tokens`, `max_context` | SSE on; default `max_tokens`; `--max-model-len`. |

## Steps: new deployment with a gateway (known type: `llm`, `tts`)

1. Do the gateway steps in `infra/README.md`, "Add a gateway to a new deployment".
2. In `gateway.tf`, give every path an `options` operation with `security = []` (the CORS preflight has no key). Copy the pattern from `deployments/tts-a-kokoro-cpu/gateway.tf`.
3. Check that the backend answers CORS: `OPTIONS` with `Access-Control-Allow-Origin` and `Access-Control-Allow-Headers` that allow `x-api-key`. vLLM and Kokoro-FastAPI do it by default. For a custom image, add CORS middleware (FastAPI `CORSMiddleware`, origins `*`).
4. Copy `tests/gateway.tftest.hcl`; it checks the `options` operations. Run `terraform init -backend=false && terraform test`.
5. Add the `ui` output to `outputs.tf`.
6. Tell the user to apply (and run `scripts/gateway-streaming.py` if streaming). The agent does not apply.
7. After the apply: `./scripts/ui-deploy.py --config-only` adds the tab, with no rebuild.

## Steps: new model type (for example `stt`)

1. Add `ui/src/panels/<Type>.tsx`. Copy the structure of `Tts.tsx`: use `call()` and `curlFor()` from `api.ts` (key, 429 retry, CORS error text), and `Timings`, `Status`, `Curl` from `components.tsx`.
   - STT (`POST /v1/audio/transcriptions`, OpenAI-compatible): send `FormData` with `file` and `model`. Do not set `Content-Type` (the browser sets the multipart boundary). Inputs: file upload and a record button (`MediaRecorder`). On iOS Safari, `MediaRecorder` makes `audio/mp4`. Streaming (`stream=true`) returns SSE: use `readSse()` from `sse.ts`.
2. Register the panel in `ui/src/panels/index.ts`.
3. Add the type to the `features` table above.
4. Add the routes to `ui/mock-server.mjs`, so the panel works without GCP.
5. Add unit tests for new pure logic in `ui/src/*.test.ts`.
6. Build with `./scripts/ui-deploy.py` (full: new code needs a build).

## Steps: a changed feature or route

Change the `ui` output (and the panel if it needs a new key). After the apply, run `./scripts/ui-deploy.py` (full when `ui/` changed, else `--config-only`).

## Check (the agent runs these)

```sh
cd ui && npm install && npm test && npm run build
terraform fmt -recursive -check
cd deployments/<name> && terraform init -backend=false && terraform test
```

Local check in a browser:

```sh
cd ui && npm run mock                                              # terminal 1: fake gateways, key "test"
cd ui && cp public/models.mock.json public/models.json && npm run dev   # terminal 2
```

Open the printed URL and enter the key `test`. `npm run dev` listens on all interfaces, so a phone on the same network can open `http://<mac-ip>:5173`. To test real deployments locally instead, run `./scripts/ui-deploy.py --local`.

## Pitfalls

- A new `ui` output is not in the state until the deployment is applied. `ui-deploy.py` then prints `skip <name>: Output "ui" not found`.
- "Request ... failed. Most likely a wrong API key" in the UI: the gateway rejects a wrong key without CORS headers, so the browser hides the status. Check the key first (`terraform -chdir=infra/core output -raw api_key`). Else the preflight failed: check the `options` operation in `gateway.tf` and the backend CORS. For Vertex AI `:rawPredict`, see `infra/README.md`, "Test UI" (proxy fallback).
- Stream playback of TTS uses `response_format = "pcm"` and Web Audio, because `MediaSource` with MP3 does not work on iOS Safari. Keep `sample_rate` right, or the audio plays at the wrong speed.
- Browsers start audio only after a user gesture. Make a `PcmPlayer` in the click handler, before the first `await`.
