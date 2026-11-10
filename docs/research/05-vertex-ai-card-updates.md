# Card updates for Vertex AI

Date: 2026-11-10. Card: "Update tickets to Vertex AI usage". Source: `04-vertex-ai.md`.

This file holds the new text for each board card. Paste each "Description" into its card. The agent cannot edit other cards.

Summary:

| Card | Action |
|---|---|
| 1. TTS-A Kokoro (CPU) | Done. No change. It stays on Cloud Run. |
| 2. LLM-A Gemma 4 on Cloud Run | No change. The Vertex AI version is the new card B. |
| New A. Vertex AI foundation | Create. It blocks cards B, 3, 4, 5 and 6. |
| New B. LLM-A on Vertex AI | Create. |
| 3. LLM-B | Replace the description. Target Vertex AI. |
| 4. STT-A | Replace the description. Target Vertex AI. |
| 5. STT-B | Replace the description. Target Vertex AI. |
| 6. TTS-B | Replace the description. Target Vertex AI. |
| 7. Measurements | Replace the description. Add Cloud Run compared with Vertex AI. |

Rules for all Vertex AI cards:

1. Each model has its own folder under `deployments/` with its own state. The folder calls `infra/modules/vertex-model/`.
2. Endpoints are private. There is no public access.
3. Use `min_replica_count = 0` (Preview) and a short idle time. Clients retry on HTTP 429 after idle.
4. Weights load from `AIP_STORAGE_URI` (`gs://<project_id>-models/<TARGET_DIR>/`). There is no `/models` mount.
5. The container follows the Vertex serving contract: port `$AIP_HTTP_PORT` (8080), a health route and 1 predict route, or `:invoke` with `/*`.

## New A. Vertex AI foundation (bootstrap + module)

Title: `A. Vertex AI foundation: bootstrap + vertex-model module`

Description:

```
Add the shared Vertex AI parts. This card blocks all other Vertex AI cards.

Scope:
- Bootstrap: enable aiplatform.googleapis.com. Confirm the L4 (g2-standard-*) quota for Vertex AI prediction in europe-west4.
- New module infra/modules/vertex-model/: model upload (custom container), dedicated private endpoint, deploy, and a service account with roles/storage.objectViewer on the weights bucket.
- Select the deploy method: Terraform only, or Terraform plus a gcloud step for custom containers. Check if google_vertex_ai_endpoint_with_model_garden_deployment accepts a custom image in provider ~> 8.10.
- Scale to zero: min_replica_count = 0 (Preview) and a short idle time. Write the HTTP 429 retry rule in the module README.
- Weights: load from AIP_STORAGE_URI. Select a copy at start or vLLM --load-format runai_streamer.
- Keep the anti-goals: no public access, no model lists in one root.

Done when: terraform test passes for the module with a mock provider, and the module README has the routes, the 429 rule and the weights flow.

Why: Vertex AI needs a second module next to model-service. All models except TTS-A move to Vertex AI (user decision, 2026-11-10).

Context:
See docs/research/04-vertex-ai.md (Vertex serving contract, Images, Next cards, Open questions 2, 3, 5 and 7). Apply against real GCP is run by the user.
```

## New B. LLM-A on Vertex AI

Title: `B. LLM-A: Gemma 4 12B QAT on stock vLLM on Vertex AI (L4)`

Description:

```
Move LLM-A from Cloud Run to a Vertex AI endpoint.

Scope:
- New folder deployments/llm-a-gemma4-12b-vllm-vertex/. It calls infra/modules/vertex-model/.
- Stock vllm/vllm-openai, flags only. Add --host 0.0.0.0 --port 8080. Use the same weights folder as the Cloud Run version (gs://<project_id>-models/<TARGET_DIR>/).
- Machine: g2-standard-8 with 1 NVIDIA_L4, shared memory 16384 MB, deployment timeout 1800 s.
- Routes: health /health. Predict /v1/chat/completions through :rawPredict, or :invoke with /* for the full OpenAI API.

Done when: a chat call returns text, the endpoint scales to 0, cold start is written down, and terraform destroy removes it.

After that, the user decides to keep or destroy the Cloud Run version (deployments/llm-a-gemma4-12b-vllm/) as a reference.

Depends on card A (Vertex AI foundation).

Why: It is the first model on Vertex AI. Stock vLLM fits the contract with flags only, so it proves the module.

Context:
See docs/research/04-vertex-ai.md (The Vertex serving contract, Images, Next cards). Not checked: :invoke with streamed (SSE) responses.
```

## 3. LLM-B

Title: `3. LLM B: Qwen3.5-9B FP8 in own FastAPI + AsyncLLMEngine image on Vertex AI (L4)`

Description:

```
First custom container for an LLM. Target: Vertex AI endpoint.

Scope:
- deployments/llm-b-qwen35-9b-fastapi/ with image/ (Dockerfile FROM vllm/vllm-openai, app.py, cloudbuild.yaml). The folder calls infra/modules/vertex-model/.
- app.py: FastAPI app that runs vLLM AsyncLLMEngine in the same process. Routes /health and /generate, plus 1 or 2 custom routes (for example /extract with a JSON schema and guided decoding).
- Vertex contract: listen on 0.0.0.0:$AIP_HTTP_PORT (8080). Health route /health. Use 1 predict route, or :invoke with /* to reach all routes.
- Weights: load from AIP_STORAGE_URI (gs://<project_id>-models/qwen3.5-9b-fp8/). Uvicorn with 1 worker.
- Build with Cloud Build and push to Artifact Registry.

Done when: the custom route returns valid JSON through the Vertex endpoint, the image builds in Cloud Build, cold start is written down, and the endpoint scales to 0.

Depends on card A (Vertex AI foundation) and card 2 (weights copy job).

Why: The user asked for a deployment with own Python code around vLLM. This card proves the custom container path on Vertex AI that STT-B uses.

Context:
See docs/research/04-vertex-ai.md (The Vertex serving contract, Fit per model), docs/research/02-open-weight-models.md (section B, AsyncLLMEngine skeleton) and docs/research/01-serverless-inference-on-gcp.md (Custom vLLM container, Dockerfile example). Check the AsyncLLMEngine API against the vLLM version in the image. Upgrade path: Qwen3.8-27B FP8 on RTX PRO 6000. Not checked: exact HF repo name of the Qwen3.5-9B FP8 checkpoint.
```

## 4. STT-A

Title: `4. STT-A: Qwen3-ASR-1.7B on stock vLLM on Vertex AI (L4)`

Description:

```
First STT deployment. Target: Vertex AI endpoint. It reuses the LLM-A Vertex setup (card B).

Scope:
- deployments/stt-a-qwen3-asr-vllm/: vllm/vllm-openai image, 1 L4, calls infra/modules/vertex-model/. Weights from AIP_STORAGE_URI (copied with the weights job).
- OpenAI-compatible /v1/audio/transcriptions. It takes a multipart upload, so use :rawPredict or :invoke with /*.
- Shared public endpoints limit the body to 1.5 MB. Use a dedicated endpoint, or send large audio as a GCS path.
- First check if the stock image has the vllm[audio] extra. If not, add a small image/ folder (FROM vllm/vllm-openai + uv pip install --system "vllm[audio]==<same version>").

Done when: a transcription request with a short audio file returns text through the Vertex endpoint, the real-time factor and cold start are written down, and the endpoint scales to 0.

Depends on card A (Vertex AI foundation) and card 2 (weights copy job). Card B first is best: same image, only flags change.

Why: It is the most accurate open STT model in the review, and it uses the same image and module as LLM-A.

Context:
See docs/research/04-vertex-ai.md (Fit per model: medium fit), docs/research/03-speech-models.md (STT candidates, notes for STT-A). Not checked: the vLLM version that supports Qwen3-ASR, the exact HF repo name, the sample rate, and multipart through :invoke.
```

## 5. STT-B

Title: `5. STT-B: Whisper large-v3-turbo in own faster-whisper + FastAPI image on Vertex AI (L4)`

Description:

```
Custom container example for speech. Target: Vertex AI endpoint.

Scope:
- deployments/stt-b-whisper-turbo-fastapi/ with image/ (Dockerfile, app.py, cloudbuild.yaml). The folder calls infra/modules/vertex-model/.
- app.py: FastAPI with faster-whisper. Load the model 1 time at start, compute_type="float16" on L4, 1 Uvicorn worker. Listen on 0.0.0.0:$AIP_HTTP_PORT (8080). Health route /health.
- Predict route: accept JSON {"instances": [{"audio_uri": "gs://..."}], "parameters": {...}} through :predict and return {"predictions": [...]}. Add 1 custom option (for example VAD or word timestamps).
- Optional: also expose /v1/audio/transcriptions through :invoke, so one client works for STT-A and STT-B.
- Weights from AIP_STORAGE_URI, or inside the image if small enough (decide in the spec).

Done when: a transcription request with a GCS audio path returns text with the custom option, the image builds in Cloud Build, real-time factor and cold start are written down, and the endpoint scales to 0.

Depends on card A (Vertex AI foundation). Reuses the custom image flow from card 3 if that card is done first.

Why: It shows a non-vLLM custom Python server, with 99 languages and room for custom audio logic (VAD, timestamps, diarization).

Context:
See docs/research/04-vertex-ai.md (Fit per model: good fit, The Vertex serving contract) and docs/research/03-speech-models.md (STT candidates, notes for STT-B). Whisper large-v3-turbo: 0.8B, MIT, WER about 7.6%. The service account needs read access to the audio bucket.
```

## 6. TTS-B

Title: `6. TTS-B: Qwen3-TTS-1.7B on vLLM-Omni on Vertex AI (L4)`

Description:

```
TTS with voice cloning and streaming on the vLLM family. Target: Vertex AI endpoint. This is the highest risk card on Vertex AI.

Scope:
- First do a spike: check that a Vertex endpoint returns audio bytes through :rawPredict or :invoke, and check if streamed audio works. If streaming does not work, report it before more work.
- deployments/tts-b-qwen3-tts-vllm-omni/: run `vllm serve <model> --omni --host 0.0.0.0 --port 8080`, 1 L4, calls infra/modules/vertex-model/. Weights from AIP_STORAGE_URI.
- First check if vLLM-Omni has a release image. If not, add image/ with FROM vllm/vllm-openai and install vllm-omni with a matching version.
- OpenAI-compatible /v1/audio/speech through :invoke with /*. Test fixed voices, then voice cloning with the Base variant and a short clip.

Done when: /v1/audio/speech returns audio through the Vertex endpoint, the streaming result (works or not) is written down, time to first audio and cold start are written down, and the endpoint scales to 0.

Depends on card A (Vertex AI foundation) and card 2 (weights copy job).

Why: It is the GPU TTS pick (Apache 2.0) with voice cloning and streaming. It uses the same OpenAI /v1/audio/speech API as TTS-A (Cloud Run), so the 2 can be compared with 1 client.

Context:
See docs/research/04-vertex-ai.md (Fit per model: highest risk, Open question 6), docs/research/03-speech-models.md (TTS candidates, notes for TTS-B), the vLLM-Omni Speech API doc (https://docs.vllm.ai/projects/vllm-omni/en/latest/serving/speech_api/) and recipe (https://recipes.vllm.ai/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice). Not checked: a vLLM-Omni image, the vLLM-Omni version for Qwen3-TTS, and audio streaming through Vertex AI.
```

## 7. Measurements

Title: `7. Measure cold start, speed and cost of all deployments (Cloud Run and Vertex AI)`

Description:

```
Compare the deployed services and endpoints with the same method.

Scope:
- A small script (for example scripts/bench.py) that, for each service or endpoint: waits until it is at 0 instances or replicas, sends 1 request and records the cold start, then sends warm requests.
- Vertex AI: the first request after idle gets HTTP 429. Record the time from the first request to the first good response, with retries.
- Metrics: cold start time, tokens per second (LLM), real-time factor (STT), time to first audio (TTS), cost per hour from the billing export or the price list. For Vertex AI also record the minimum billed time for 1 test session (idle time before scale down).
- Compare Cloud Run with Vertex AI for the same model: LLM-A on both.
- Write the results in docs/research/06-measurements.md, with the date, region, image versions and settings.
- Try 1 or 2 cold start improvements (for example Run:ai Model Streamer, a shorter Vertex idle time, smaller weights) and record the effect.

Done when: the table covers every deployed service and endpoint, it has the Cloud Run compared with Vertex AI row for LLM-A, and the doc lists the best cold start setting found.

Why: Scale to zero only works for the user if the cold start is acceptable. Vertex AI cold start is minutes, not seconds, so the numbers decide if the move is acceptable.

Context:
See docs/research/04-vertex-ai.md (Vertex AI compared with Cloud Run) and docs/research/01-serverless-inference-on-gcp.md (Model weights and cold start, Cost control). Run after card 2 and card B; add each other service when it exists. Cloud Run services: call with gcloud auth print-identity-token. Vertex endpoints: call with gcloud auth print-access-token.
```

Note: the old card text named `docs/research/04-measurements.md`. That number is now used by `04-vertex-ai.md` and this file uses 05, so the new name is `06-measurements.md`.
