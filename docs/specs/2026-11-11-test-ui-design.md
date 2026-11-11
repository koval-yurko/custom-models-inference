# Design: Web UI to test the deployed models

Date: 2026-11-11. Status: approved by the user in chat (playback, mockups, "start implementation").

## Intent

The user tests each model by hand with `curl` today. A web UI must replace that: one tab for each model, the main features of each model type, and the numbers that show if the deployment works (HTTP status, time to first byte or token, total time). The user also opens it on a phone.

## Decisions (by the user)

1. Static React app only. No backend. A Cloud Function only for a case that a browser cannot do alone.
2. The API key is entered in the UI and kept in `localStorage`.
3. One tab in the header for each model.
4. TTS: play or download the audio. Wait for the whole file, or play while it streams.
5. LLM: chat layout (option A of the mockups), with streaming on or off.
6. CORS is added to the gateways. The user applies again.
7. No own domain. The URL is `https://storage.googleapis.com/<project_id>-ui/index.html`.
8. A skill updates the UI when a new model or feature comes. The UI gets the real URLs from shared config, not from code.

## How it works (agent decisions)

- Config: each deployment with a gateway has a Terraform output `ui` (id, title, type, base_url, model, features). `scripts/ui-deploy.py` reads the outputs, writes `models.json`, builds the app and uploads both. The model data stays in the deployment folder (one folder per model). A gateway URL change needs only `--config-only`, no rebuild.
- Hosting: public bucket in `infra/core/ui.tf`, `roles/storage.legacyObjectReader` for `allUsers` (read, no list). Hash routing (`#/<id>`), so no rewrite rules. `index.html` and `models.json` have `Cache-Control: no-cache`.
- CORS: an `options` operation without the key on each gateway path. The backend answers the preflight. Kokoro-FastAPI has CORS on by default. vLLM sends CORS headers by default; not verified through Vertex AI `:rawPredict`. Fallback: a Cloud Run proxy for the LLM gateway (also fixes the open ID-token question).
- TTS streaming uses `pcm` and Web Audio, because `MediaSource` with MP3 does not work on iOS Safari. After the stream, the PCM is wrapped as WAV for replay and download.
- LLM: SSE with `stream_options.include_usage` for the token count. The UI retries HTTP 429 every 30 s (Vertex AI at 0 replicas), at most 60 times, with Stop.
- Each panel shows the request as `curl` (key as `$KEY`), so a test in the UI can be repeated in the terminal.
- STT has no panel yet (no STT model is deployed). An unknown type shows a note. The `model-ui` skill says how to add the panel.

## Non-goals

- No login and no user accounts. The shared API key is the only access control.
- No custom domain, no load balancer.
- No request history or saved results.

## Open points

- CORS through Vertex AI `:rawPredict` is not verified. Check it on the first LLM deployment.
- The CORS origin is `*`. The bucket origin `storage.googleapis.com` is shared by all public buckets, so an origin limit would not protect much. The API key controls access.
