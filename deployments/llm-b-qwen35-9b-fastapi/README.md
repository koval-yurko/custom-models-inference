# LLM-B: Qwen3.5-9B FP8 in an own FastAPI + vLLM image, on Vertex AI and Runpod

The deployment calls the module `infra/modules/model` with `platforms = ["vertex", "runpod"]` (see `infra/README.md`, section "Module: model (platforms)"). Vertex AI is the default platform for the old paths.

- Model `RedHatAI/Qwen3.5-9B-FP8-dynamic` (Apache 2.0, about 14 GB with the MTP and vision files). Qwen publishes no FP8 build of the 9B model. The Red Hat build is the FP8 build that vLLM documents, and it has the most downloads.
- Image `image/`: `FROM vllm/vllm-openai:v0.33.0` and `app.py`. `app.py` is a FastAPI app that runs the vLLM engine (`AsyncLLM`, the v1 `AsyncLLMEngine`) in the same process. Uvicorn runs 1 process. It follows the container contract: it reads `PORT` (else `AIP_HTTP_PORT`, else 8080) and `MODEL` (else `AIP_STORAGE_URI`).
- Vertex AI: private dedicated endpoint in `us-central1`, `g2-standard-8`, 1 `NVIDIA_L4`, 0 to 1 replica, 300 s idle time. Vertex AI gives the weights path as `AIP_STORAGE_URI` (`gs://<project_id>-models/qwen3.5-9b-fp8/`), and vLLM streams the weights from GCS (`runai_streamer`). The KV cache is FP8.
- Runpod (since 2026-11-24): 1 load balancing endpoint `llm-b-qwen35-9b-fastapi`, pools `AMPERE_24` and `ADA_24`, only L4 ($0.75/h serverless) and RTX 4090 ($1.34/h) in EU-RO-1 (`excluded_types` removes the A5000 and the RTX PRO 6000 MIG slice; the RTX 3090 is not in EU-RO-1; Runpod has no GPU order, so a worker starts on any of them with capacity), FlashBoot off, 0 to 1 worker, 300 s idle time. The image comes from the `models` repo with the `infra/core` registry credential `gcp-models`. The weights are on 1 network volume in `EU-RO-1` (40 GB: the S3 copy needs about 2 times the largest file, see below; 1 copy only, because each copy bills $0.07/GB/month, see `docs/research/11-weights-storage-options.md`) at `/runpod-volume/qwen3.5-9b-fp8` (env `MODEL`). `scripts/runpod-weights.py` copies them there from GCS. EU-RO-1 had the most 24 GB stock of the data centers with the S3 API on 2026-11-27 (RTX 4090 MEDIUM, L4 LOW). The KV cache uses the model dtype (`KV_CACHE_DTYPE=auto`), because the RTX 3090 (Ampere) has no native FP8. vLLM runs the FP8 weights on Ampere as W8A16.
- Vertex AI routes: no `predict_route`, so `:invoke` reaches every route of `app.py`. `:predict` and `:rawPredict` are off.
- Public API Gateway `llm-b-qwen35-fastapi` checks `x-api-key` and lets through only `POST /generate` and `POST /extract`. Each path is there 3 times: the old path (Vertex AI), `/vertex/...` and `/runpod/...`. Behind it, the private Cloud Run service `llm-b-qwen35-fastapi-proxy` forwards each call to the platform and adds CORS headers. The test UI has a tab for it (type `llm-routes`) with a platform picker.
- Direct calls to the Vertex AI endpoint need `aiplatform.endpoints.predict` on the project.

| Route | Body | Answer |
|---|---|---|
| `GET /health`, `GET /ping` | - | `200 {"status":"ok"}` when the engine is ready. While the model loads: `503` (Vertex AI) or `204` (Runpod). The Runpod load balancer probes `/ping` over IPv4, so `app.py` listens on `0.0.0.0`. |
| `POST /generate` | `{"prompt": "...", "max_tokens": 512, "temperature": 0.7}` | `{"text": "..."}` |
| `POST /extract` | `{"text": "...", "schema": {...}, "max_tokens": 1024}` | `{"data": {...}}`: JSON that matches the schema. vLLM structured outputs force the format. Without `schema`, the app uses its default schema (people, organizations, places, dates). |

Both POST routes use the chat template with thinking off. Settings come from env values in `main.tf`: `SERVED_MODEL_NAME`, `MAX_MODEL_LEN` (16384), `KV_CACHE_DTYPE` (default `fp8`; `auto` on Runpod).

## Deploy

Do `infra/core` first (see `infra/README.md`). Its `gateways.tf` has the gateway API `llm-b-qwen35-fastapi`, and its `runpod_registry.tf` has the registry credential `gcp-models`. Run the commands from the repo root.

0. Sync the HCP workspace (`custom-models-llm-b-qwen35-9b-fastapi`). Then check the weights folder and the L4 quota. Fix every FAIL. The weights check fails until step 1 is done.
   ```sh
   ./scripts/hcp-sync.py
   ./scripts/preflight.py --weights qwen3.5-9b-fp8 --l4
   ```
1. Copy the weights to GCS (13 GiB, about 9 minutes). Skip this step when the folder already has files.
   ```sh
   gcloud storage ls gs://$GCP_PROJECT_ID-models/qwen3.5-9b-fp8/
   gcloud run jobs execute weights-copy --wait \
     --update-env-vars HF_REPO=RedHatAI/Qwen3.5-9B-FP8-dynamic,TARGET_DIR=qwen3.5-9b-fp8
   ```
2. Build the image with Cloud Build (about 14 minutes). It pushes to the `models` repo. The tag must be the same as `image_tag` in `variables.tf`. Build before the apply: Runpod checks at create that the template image exists.
   ```sh
   gcloud builds submit deployments/llm-b-qwen35-9b-fastapi/image \
     --config=deployments/llm-b-qwen35-9b-fastapi/image/cloudbuild.yaml \
     --substitutions=_REGION=$GCP_REGION,_TAG=0.2.3 --region=$GCP_REGION
   ```
3. Apply. Step 0 (`hcp-sync.py`) made the Runpod secrets `slack_bot_token` and `slack_channel` (see [Runpod (own images: Slack from the container)](../../infra/README.md#runpod-own-images-slack-from-the-container)). Without them, the worker sends no Slack message. The apply makes the Vertex AI endpoint, the Runpod volumes, template and endpoint, the CORS proxy and the gateway.
   ```sh
   cd deployments/llm-b-qwen35-9b-fastapi && terraform init && terraform apply && cd ../..
   ```
4. Copy the weights from GCS to the Runpod volume in EU-RO-1 (Cloud Build job; see `infra/README.md`, section "Copy weights to a Runpod volume"). Do this before the first `/runpod/` call.
   ```sh
   ./scripts/runpod-weights.py deployments/llm-b-qwen35-9b-fastapi --dry-run
   ./scripts/runpod-weights.py deployments/llm-b-qwen35-9b-fastapi --cloud
   ```
5. Upload and deploy the Vertex AI model. It takes up to 45 minutes. Runpod has no step here: its endpoint is ready after the apply.
   ```sh
   ./scripts/deploy.py deploy deployments/llm-b-qwen35-9b-fastapi
   ./scripts/deploy.py status deployments/llm-b-qwen35-9b-fastapi   # vertex: deployed, runpod: deployed
   ```
6. Update the test UI (the tab gets the platform picker).
   ```sh
   ./scripts/ui-deploy.py
   ```

To change the code:

1. Raise `image_tag` in `variables.tf` and build with the new `_TAG` (step 2).
2. Run `./scripts/check.py`. Then run a plan and read it:
   ```sh
   cd deployments/llm-b-qwen35-9b-fastapi && terraform plan && cd ../..
   ```
   Expected: the Runpod template is replaced (a new template name), and the Runpod endpoint gets the new template and a new name. On 2026-11-26 the endpoint was updated in place and kept its ID; a replace gives it a new ID and the proxy gets the new URL in the same apply.
3. Check the FlashBoot slots. The replace makes the new endpoint before it deletes the old one, and the account allows 3 endpoints with FlashBoot. Open Runpod > Serverless and count the endpoints with FlashBoot on. If there are 3, turn FlashBoot off on this endpoint first.
4. Run the apply (step 3), then the Vertex AI model again:
   ```sh
   ./scripts/deploy.py undeploy deployments/llm-b-qwen35-9b-fastapi --platform vertex
   cd deployments/llm-b-qwen35-9b-fastapi && terraform apply && cd ../..
   ./scripts/deploy.py deploy deployments/llm-b-qwen35-9b-fastapi
   ```
   Skip the 2 `deploy.py` commands when only Runpod changes.

## First plan after the move to the model module (2026-11-24)

The resources moved from `vertex-model`, `gateway.tf` and `cors_proxy.tf` into `infra/modules/model` (`moved.tf`, and `infra/modules/platform-vertex/moved.tf` for the last step). Build the image `0.2.1` first (step 2). Then run a plan and read it before you apply:

```sh
cd deployments/llm-b-qwen35-9b-fastapi && terraform init && terraform plan
```

Expected:

- Moves only (`has moved to`): the endpoint, its service account and bucket IAM member, the CORS proxy module, the gateway service account, the API config, the gateway, and `module.scale_alerts` to `module.scale_alerts[0]`. If the state still has `google_project_iam_member.predict` without an index, it also moves to `predict[0]` (a `moved` block of the proxy module).
- A new API config (the paths `/vertex/...` and `/runpod/...`, and `x-google-backend` on each operation), the old API config destroyed after it, and the gateway updated in place.
- An in-place update of the proxy service `llm-b-qwen35-fastapi-proxy` (env `TARGETS`, the Runpod key secret, the timeout).
- New: 3 Runpod volumes, the Runpod template and endpoint, the `secretAccessor` member of the proxy SA on the secret `runpod-api-key`. No Runpod Slack alert: the container posts its own messages.
- No replace of `google_vertex_ai_endpoint`, `google_api_gateway_gateway` or a service account. If the plan shows one, stop and check `moved.tf` against `terraform state list`.

After the apply, do steps 4 to 6 of [Deploy](#deploy). The deployed Vertex AI model keeps the image `0.1.1` until the next `undeploy` and `deploy`; `0.1.1` works on Vertex AI.

## Test

Warning: a call at 0 replicas starts a GPU (Vertex AI: an L4 at about $1 per hour; Runpod: billed per second until the 300 s idle time ends).

Before a Runpod test, check the Runpod balance (console > Billing): the account is prepaid, and below $0.01 Runpod starts no worker and holds the call until the proxy answers `429`. Then check the GPU stock in EU-RO-1, the data center of the volume. A worker starts only there. When the 24 GB GPUs (RTX 4090, RTX 3090, L4, RTX A5000) are all `LOW` or missing, the call can wait for a long time (see the 2026-11-26 row in [Cold start](#cold-start)). The stock is a hint, not a promise.

```sh
for dc in EU-RO-1; do
  curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" "https://api.runpod.io/v2/catalog/datacenters/$dc?include=GPU_AVAILABILITY" |
    python3 -c "import json,sys; d=json.load(sys.stdin); print('$dc', [(g['name'], g['availability']) for g in d['gpuAvailability'] if g['name'] in ('RTX 4090','RTX 3090','L4','RTX A5000')])"
done
```

At 0 replicas, Vertex AI returns HTTP 429 at once. Runpod holds the call while a worker starts; when no answer comes in 280 s, the proxy answers `429`. The loop sends the call again every 30 s, for at most 30 minutes. It prints the time to the first `200`: this is the cold start.

```sh
cd deployments/llm-b-qwen35-9b-fastapi
GW=$(terraform output -raw gateway_url)
KEY=$(terraform -chdir=../../infra/core output -raw api_key)
P=runpod   # or vertex
start=$(date +%s)
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/out.json -w '%{http_code}' -X POST "$GW/$P/extract" \
    -H "x-api-key: $KEY" -H "Content-Type: application/json" \
    -d '{"text":"Ada Lovelace met Charles Babbage in London on 5 June 1833. Both later worked with the Royal Society."}')
  [ "$code" != 429 ] && break
  sleep 30
done
echo "$code after $(( $(date +%s) - start )) s"; python3 -m json.tool /tmp/out.json
```

Expected: `200` and valid JSON, for example `{"data": {"people": ["Ada Lovelace", "Charles Babbage"], "organizations": ["Royal Society"], ...}}`. A `504` means the gateway deadline (300 s) passed while a request ran: send the call again.

Own schema and `/generate`:

```sh
curl -s -X POST "$GW/$P/extract" -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d '{"text":"Order 42: 3 red chairs, total 120 EUR.","schema":{"type":"object","properties":{"order_id":{"type":"integer"},"items":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"qty":{"type":"integer"}},"required":["name","qty"]}},"total":{"type":"number"},"currency":{"type":"string"}},"required":["order_id","items","total","currency"]}}'
curl -s -X POST "$GW/$P/generate" -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d '{"prompt":"Say hello in 5 words.","max_tokens":32}'
```

Direct call to the Vertex AI endpoint (no gateway):

```sh
BASE="https://$(terraform output -raw endpoint_dns)/v1/projects/$GCP_PROJECT_ID/locations/$GCP_REGION/endpoints/$(terraform output -raw endpoint_id)"
curl -s -X POST "$BASE/invoke/generate" -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" -d '{"prompt":"Say hello in 5 words.","max_tokens":32}'
```

## Cold start

Write the results here after each measured cold start. "Cold start" is the time from the first call at 0 replicas to the first `200` (the loop above prints it). Vertex AI writes no container log for this endpoint (see below), so there is no split into weights load and engine init.

| Date | Image tag | Event | Time | Notes |
|---|---|---|---|---|
| 2026-11-14 | 0.1.0 | First deploy (`vertex.py deploy`: model upload, node start, image pull, weights load, engine init) | 1398 s (23 min) | 1 replica up after the deploy. |
| 2026-11-14 | 0.1.0 | Scale up from 0 (first call 22:34:32 UTC, through the gateway, retry every 30 s) | failed: `429` for 1825 s, replicas stayed at 0 | Cause: no GPU stock. The deployed model status said `Machine type temporarily unavailable ... "g2-standard-8" ... "nvidia-l4"`. The project quota was fine. This is not a start-up time; measure again when a node is available. |
| 2026-11-16 | 0.1.0 | Scale up from 0 (first call 15:07:06 UTC, through the gateway, retry every 30 s) | **648 s (10.8 min)** to the first `200`; the scale-up began about 30 s before the first call | The deployed model status showed failed attempts first: `System error`, then `Machine type temporarily unavailable`, then `Model server never became ready`. Vertex AI retried by itself, and the next attempt answered. Plan for 10 to 30 min, or a failure when no L4 is free. |
| 2026-11-24 | 0.2.1, 0.2.2 | Runpod scale up from 0 (`/runpod/extract`, first call 13:26:45 UTC, retry every 30 s; again at 14:18:45 with 0.2.2) | failed: `429` for 25 min, then stopped by hand | RTX 4090, EU-RO-1, network volume. Container start to `engine ready`: 141 s (13:31:00 to 13:33:21). The load balancer never routed a call: `https://<id>.api.runpod.ai/health` timed out, and Runpod stopped the container every 9 to 10 min. 0.2.2 logs each health code change: no health request reached the container. The cause is on the Runpod side (see the STT-A README). |
| 2026-11-26 | 0.2.3 | Runpod scale up from 0 (`/runpod/extract` through the gateway, retry every 30 s), 2 runs: 12:21:59 UTC with FlashBoot on, 13:07:30 UTC with FlashBoot off | failed: `429` for 36 min, then for 48 min; no `200` | No container started, so the `/ping` fix is not tested on Runpod yet. Run 1: 1 worker (RTX 4090, EU-RO-1) stayed IDLE with no uptime, then THROTTLED 12:45 to 12:55. Run 2: 1 worker THROTTLED 13:10 to 13:30, then 0 workers. Cause (found 2026-11-27): the prepaid Runpod balance was below $0 (-$0.02), so Runpod started no worker; a 2026-11-27 run had the same result with HIGH RTX 4090 stock, and the endpoint create failed with `You must have at least $0.01 in your account balance`. Check the balance first (Runpod console > Billing). |
| 2026-11-27 | 0.2.3 | Runpod scale up from 0 (`/runpod/extract` through the gateway, retry every 30 s), new endpoint `7k3hvqfzebg9wl`, FlashBoot off, balance $9.97 | **411 s (6.9 min)** to the first `200`: try 1 got the proxy `429` at 281 s, try 2 got `200` at 411 s. A warm call took 1.4 s | First Runpod answer for LLM-B. 1 worker, RTX 4090, EU-RO-1 (stock MEDIUM), weights from the network volume (13.04 GiB, FUSE). The worker started about 10 s after the first call. The load balancer probed `GET /ping` over IPv4 (`100.64.0.x`), and the app answered `204` while vLLM loaded: the 0.0.0.0 and `/ping` fix works. The answer JSON was correct (people, organizations, places, dates). Scale to 0: the worker stopped at 11:17:40 UTC, 300 s after the last request. The last request was a `GET /health` of the `scale-watch` job at 11:12:29, not the test call at 11:07, so the probe of a new endpoint keeps the GPU up for about 5 more minutes. Kept live after the test (`workers_max: 1`). |

## Check scale to zero

Send no requests for about 15 minutes (idle time 300 s plus the check interval). Then the replica count must be `0`: open the endpoint in the console (Vertex AI > Online prediction > Endpoints) and look at the replica chart. The next call must return `429` first.

Slack: after a cold start, the channel gets `🟢 LLM-B Qwen3.5 9B is ready`. After the scale down, it gets `⚪ LLM-B Qwen3.5 9B scaled to 0` (300 s idle time, then the shutdown). For Runpod, the container itself posts `🟢 LLM-B Qwen3.5 9B on Runpod is ready` after the engine loads, and `⚪ LLM-B Qwen3.5 9B on Runpod scaled to 0` at its shutdown. It needs the Runpod secrets `slack_bot_token` and `slack_channel`. See [Scale notifications (Slack)](../../infra/README.md#scale-notifications-slack).

## Park the Runpod endpoint

The Runpod settings are in `deploy.yaml` (see [deploy.yaml](../../infra/README.md#deployyaml-per-deployment)). Edit the file, then apply (step 3).

- Park: set `workers_max: 0`. The endpoint, the template and the volume stay, but no worker starts. To serve again, set `workers_max: 1`.
- Take Runpod out of service: set `serve: false`. The endpoint is destroyed, and the gateway has no `/runpod/` path. The template and the volume with the weights stay. To serve again, set `serve: true`. Check the Runpod balance first (`./scripts/preflight.py`): Runpod refuses to create an endpoint below $0.01.

## Destroy

Undeploy the Vertex AI model first. Vertex AI does not delete an endpoint that has a deployed model.

```sh
./scripts/deploy.py undeploy deployments/llm-b-qwen35-9b-fastapi --platform vertex
cd deployments/llm-b-qwen35-9b-fastapi && terraform destroy
```

The destroy also deletes the Runpod volume and its weights. The GCS weights and the image stay. Delete the image with `gcloud artifacts docker images delete $GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/models/llm-b-qwen35-9b-fastapi --delete-tags`.

## Verified on 2026-11-14

1. Cloud Build pulled `vllm/vllm-openai:v0.33.0` from Docker Hub and pushed `models/llm-b-qwen35-9b-fastapi:0.1.0` with the default build service account (13 min 13 s).
2. The `:invoke` URL form `<base>/invoke/<route>` and `invokeRoutePrefix = "/*"` in `v1beta1` work. `/extract` and `/generate` answered directly on the endpoint and through the gateway.
3. vLLM `runai_streamer` loads the weights from the `gs://` path that Vertex AI gives in `AIP_STORAGE_URI`.
4. `app.py` runs on the L4: `/extract` returns JSON that matches the default schema and a caller schema. `/generate` returns text. An empty `text` gets `422`.
5. The gateway rejects a call without `x-api-key` (`401`), answers the CORS preflight (`204`, `access-control-allow-origin: *`), and does not expose `/health` (`404`).
6. The deployed test UI tab `LLM-B Qwen3.5 9B (FastAPI)` sends both routes and shows the answers.

Measured warm times through the gateway: `/generate` (5 words) 0.9 s to 1.4 s; `/extract` with the default schema 2.6 s; `/extract` with a new caller schema 18.7 s on the first call (vLLM compiles the grammar for each new schema; later calls with the same schema are fast).

Not available: Vertex AI wrote no container log (stdout of `app.py` and vLLM) to Cloud Logging for this endpoint. So the cold start has no split into weights load and engine init.

Upgrade path: Qwen3.8-27B FP8 on an RTX PRO 6000. Change the weights folder, the machine and `MAX_MODEL_LEN`. `app.py` does not change.
