# Research: Vertex AI as the main platform for AI models

Date: 2026-11-10. Branch: `custom-models-mixed-deployment-target`. Builds on `01-serverless-inference-on-gcp.md`.

## Decision by the user (2026-11-10)

1. TTS-A Kokoro (CPU) stays on Cloud Run. It is the Cloud Run example.
2. All other models move to Vertex AI endpoints: LLM-A, LLM-B, STT-A, STT-B and TTS-B.
3. LLM-A on Cloud Run (`deployments/llm-a-gemma4-12b-vllm/`) is done. A new card moves it to Vertex AI.

This replaces the recommendation in `01-serverless-inference-on-gcp.md` ("Use Vertex AI or GKE only when a model needs more than 1 GPU").

## Vertex AI compared with Cloud Run

| Topic | Cloud Run | Vertex AI endpoint |
|---|---|---|
| Scale to zero | GA. `min_instance_count = 0`. | Preview only. `min_replica_count = 0`. The first request to an endpoint at 0 replicas gets HTTP 429 and is dropped. The default idle time before scale down is 1 hour. |
| Cost when idle | $0 | $0 with the Preview feature. With 1 minimum replica, an L4 node costs about $650 or more per month. |
| Billing unit | Per second | Per node-hour while a replica runs |
| GPUs | 1 per instance (L4 or RTX PRO 6000) | Many types, multi-GPU, multi-host, TPU |
| Cold start | Seconds, plus the model load | Minutes |
| Container | Any image, any route | It must follow the Vertex serving contract (see below) |
| Weights | GCS FUSE mount at `/models` | No mount. The container gets `AIP_STORAGE_URI` (`gs://`) and loads the weights itself. |
| Terraform | `google_cloud_run_v2_service` (our module) | `google_vertex_ai_endpoint_with_model_garden_deployment` for Model Garden models. Custom-container deploys often need a `gcloud` step. |
| Extras | None | Model Registry, Model Garden, monitoring, batch prediction |

Effects on this repo:

1. Scale to zero on Vertex AI is Preview. Clients must retry on HTTP 429 after idle.
2. With an idle time of 1 hour, each test session bills at least 1 node-hour. Set a shorter idle time.
3. Vertex AI needs a second module next to `model-service`.
4. The weights flow changes. `HF_HUB_OFFLINE=1` with `/models` does not work unchanged.

## The Vertex serving contract

Cloud Run sends every HTTP request to the container. Vertex AI puts its own API in front of the container and forwards only some calls.

| Item | Rule |
|---|---|
| Port | The container listens on `0.0.0.0:$AIP_HTTP_PORT` (default 8080). The port is the first entry of `containerSpec.ports`. |
| Health route | `containerSpec.healthRoute`, for example `/health`. It must return 200 within 10 seconds. Liveness is a TCP probe. |
| Predict route | `containerSpec.predictRoute`. This is 1 path only, for example `/v1/completions`. |
| `:predict` | Body `{"instances": [...], "parameters": {...}}`. Response `{"predictions": [...]}`. |
| `:rawPredict` | Vertex forwards the body unchanged to the predict route. There is no format rule. The OpenAI JSON of vLLM works. |
| `:invoke` (Preview) | Set `invokeRoutePrefix = "/*"` at model upload. `/invoke/foo/bar` goes to `/foo/bar`. Dedicated endpoints only. HTTP only. It turns off `:predict` and `:rawPredict`. `/*` is the only allowed value. |
| Env vars | Vertex sets `AIP_HTTP_PORT`, `AIP_HEALTH_ROUTE`, `AIP_PREDICT_ROUTE`, `AIP_STORAGE_URI`, `AIP_MODEL_NAME`, `AIP_MACHINE_TYPE`, `AIP_ACCELERATOR_TYPE` and others. Do not set an `AIP_` variable yourself. |
| Body size | Shared public endpoints limit the request and response body to 1.5 MB. |

Stock `vllm/vllm-openai` fits with flags only. It has `/health` and `/v1/completions`. Add `--host 0.0.0.0 --port 8080`. Without `:invoke`, clients get 1 route only, not the full OpenAI API.

## Images

Prebuilt images:

1. Model Garden uses a Google-built vLLM image ("an optimized and customized version of vLLM"). The official page gives no image URI. Community guides use `us-docker.pkg.dev/vertex-ai/vertex-vision-model-garden-dockers/pytorch-vllm-serve:<tag>`. This path is not confirmed in the official docs.
2. Google also has prebuilt images for SGLang, Hex-LLM (TPU), Hugging Face TGI, TEI, Hugging Face PyTorch Inference and TensorRT-LLM.

Own images:

1. Any image in Artifact Registry works if it follows the contract above.
2. Google's custom vLLM guide uses `FROM vllm/vllm-openai`, adds gcloud and an entrypoint script, and sets health route `/health` and predict route `/v1/completions`.
3. The guide loads weights with `--model=gs://<bucket>/<path>` and a service account that can read the bucket. The page does not explain how the files are downloaded.
4. GPU example in the guide: `g2-standard-8` with 1 `NVIDIA_L4`, `shared_memory_size_mb=16384`, `deployment_timeout=1800`.

## Fit per model

| Card | Platform | Fit | Notes |
|---|---|---|---|
| TTS-A Kokoro-82M, CPU | Cloud Run | Not moved | A Vertex CPU node bills per hour and starts slowly. Cloud Run is cheaper and faster for it. |
| LLM-A Gemma 4 12B QAT, stock vLLM | Vertex AI | Easy | Flags only. Gemma is also in Model Garden. The weights load changes. |
| LLM-B Qwen3.5-9B, FastAPI + vLLM | Vertex AI | Good | Own container. Add `/health` and 1 predict route, or use `:invoke` for many routes. |
| STT-A Qwen3-ASR-1.7B, stock vLLM | Vertex AI | Medium | `/v1/audio/transcriptions` takes a multipart upload. Use `:rawPredict` or `:invoke`. Send audio above 1.5 MB as a GCS path, or use a dedicated endpoint. |
| STT-B Whisper large-v3-turbo, FastAPI | Vertex AI | Good | Own code. A JSON request with a GCS audio path fits `:predict`. |
| TTS-B Qwen3-TTS-1.7B, vLLM-Omni | Vertex AI | Highest risk | The response is audio bytes, not `{"predictions"}`. Use `:rawPredict` or `:invoke`. Streamed audio through Vertex AI is not confirmed. |

## Next cards

### New: Vertex AI foundation (bootstrap + module)

This card blocks all other Vertex AI cards.

1. Bootstrap: enable `aiplatform.googleapis.com`. Confirm the L4 (`g2-standard-*`) quota for Vertex AI in `europe-west4`.
2. New module `infra/modules/vertex-model/`: model upload, dedicated private endpoint, deploy, and a service account with `roles/storage.objectViewer` on the weights bucket.
3. Select the deploy method: Terraform only, or Terraform plus a `gcloud` step for custom containers.
4. Scale to zero: `min_replica_count = 0` (Preview) and a short idle time. Write the HTTP 429 retry rule in the module README.
5. Weights: load from `AIP_STORAGE_URI`. Select a copy at start or vLLM `--load-format runai_streamer`.
6. Keep the anti-goals: no public access, no model lists in one root.
7. Done when: `terraform test` passes for the module with a mock provider.

### New: LLM-A on Vertex AI

1. New folder `deployments/llm-a-gemma4-12b-vllm-vertex/`. Stock `vllm/vllm-openai`, flags only.
2. Routes: health `/health`. Predict `/v1/chat/completions` through `:rawPredict`, or `:invoke` with `/*` for the full OpenAI API.
3. Done when: a chat call returns text, the endpoint scales to 0, and `terraform destroy` removes it.
4. After that, the user decides to keep or destroy the Cloud Run version as a reference.

### Changes to existing cards

| Card | Change |
|---|---|
| TTS-A Kokoro (CPU) | No change. Cloud Run. |
| LLM-B Qwen3.5-9B FastAPI | Target Vertex AI. The app follows the contract (`/health` plus 1 predict route), or it uses `:invoke`. |
| STT-A Qwen3-ASR vLLM | Target Vertex AI. Use `:rawPredict` or `:invoke` for the multipart upload. Send large audio as a GCS path. |
| STT-B Whisper FastAPI | Target Vertex AI. Accept JSON with a GCS audio path through `:predict`. |
| TTS-B Qwen3-TTS vLLM-Omni | Target Vertex AI. Check audio responses and streaming first. |
| Cold start measurements | Add Cloud Run compared with Vertex AI for the same model (LLM-A on both). |

All Vertex AI cards depend on "Vertex AI foundation".

## Open questions

1. Keep or destroy LLM-A on Cloud Run after the Vertex AI version works?
2. Accept Preview scale to zero with HTTP 429 on cold start? The other option is 1 minimum replica that runs all the time (about $650 or more per month for each L4 model).
3. Does `google_vertex_ai_endpoint_with_model_garden_deployment` accept a custom container image in provider `~> 8.10`?
4. What is the official URI of the Google-built vLLM image?
5. Does vLLM `runai_streamer` read `gs://` in the pinned vLLM version?
6. Does `:invoke` support streamed (SSE) responses?
7. Is L4 available for Vertex AI prediction in `europe-west4`, and what is the quota?

## Sources

- [Vertex AI autoscaling and scale to zero (Preview)](https://docs.cloud.google.com/vertex-ai/docs/predictions/autoscaling)
- [Custom container requirements for prediction](https://docs.cloud.google.com/vertex-ai/docs/predictions/custom-container-requirements)
- [Use arbitrary custom routes (`:invoke`)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/predictions/use-arbitrary-custom-routes.md.txt)
- [Deploy open models with a custom vLLM container](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/open-models/deploy-custom-vllm)
- [Use prebuilt containers for open models](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/open-models/use-prebuilt-containers)
- [gcloud ai endpoints deploy-model](https://docs.cloud.google.com/sdk/gcloud/reference/ai/endpoints/deploy-model)
- [Deploying Model Garden open models with Terraform](https://discuss.google.dev/t/new-deploying-vertex-ai-model-garden-open-models-with-terraform/271884)
- [Scale to zero and HTTP 429 behavior (third party)](https://oneuptime.com/blog/post/2026-02-17-how-to-enable-scale-to-zero-for-vertex-ai-prediction-endpoints-to-reduce-costs/view)
- [vLLM on Vertex AI, image URI (third party)](https://infocruncher.substack.com/p/large-language-model-serving-with-vllm)
