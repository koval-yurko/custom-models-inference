# LLM-B on Vertex AI: Qwen3.5-9B FP8 in an own FastAPI + vLLM image, 1 L4

First custom container of the module `infra/modules/vertex-model` (see `infra/README.md`, section "Module: vertex-model").

- Model `RedHatAI/Qwen3.5-9B-FP8-dynamic` (Apache 2.0, about 14 GB with the MTP and vision files). Qwen publishes no FP8 build of the 9B model. The Red Hat build is the FP8 build that vLLM documents, and it has the most downloads.
- Image `image/`: `FROM vllm/vllm-openai:v0.33.0` and `app.py`. `app.py` is a FastAPI app that runs the vLLM engine (`AsyncLLM`, the v1 `AsyncLLMEngine`) in the same process. Uvicorn runs 1 process.
- Private Vertex AI endpoint in `us-central1`: `g2-standard-8`, 1 `NVIDIA_L4`. It scales to zero (max 1 replica, idle time 300 s).
- Weights: `gs://<project_id>-models/qwen3.5-9b-fp8/`. Vertex AI gives the path to the container as `AIP_STORAGE_URI`. vLLM streams the weights from GCS (`runai_streamer`).
- Routes: `invoke_routes = true`, so `:invoke` reaches every route of `app.py`. `:predict` and `:rawPredict` are off.
- Public API Gateway `llm-b-qwen35-fastapi` checks `x-api-key` and lets through only `POST /generate` and `POST /extract`. Behind it, the private Cloud Run service `llm-b-qwen35-fastapi-proxy` (`cors_proxy.tf`) forwards each call to `<endpoint>/invoke/<route>` and adds CORS headers. The test UI has a tab for it (type `llm-routes`).
- Direct calls to the endpoint need `aiplatform.endpoints.predict` on the project.

| Route | Body | Answer |
|---|---|---|
| `GET /health` | - | `200 {"status":"ok"}` when the engine is ready. `503` while the model loads. |
| `POST /generate` | `{"prompt": "...", "max_tokens": 512, "temperature": 0.7}` | `{"text": "..."}` |
| `POST /extract` | `{"text": "...", "schema": {...}, "max_tokens": 1024}` | `{"data": {...}}`: JSON that matches the schema. vLLM structured outputs force the format. Without `schema`, the app uses its default schema (people, organizations, places, dates). |

Both POST routes use the chat template with thinking off. Settings come from env values in `main.tf`: `SERVED_MODEL_NAME`, `MAX_MODEL_LEN` (16384).

## Deploy

Do `infra/core` first (see `infra/README.md`). Its `gateways.tf` has the gateway API `llm-b-qwen35-fastapi`. Run the commands from the repo root.

0. Sync the HCP workspace (new: `custom-models-llm-b-qwen35-9b-fastapi`). Then check the weights folder and the L4 quota. Fix every FAIL. The weights check fails until step 1 is done.
   ```sh
   ./scripts/hcp-sync.py
   ./scripts/preflight.py --weights qwen3.5-9b-fp8 --l4
   ```
1. Copy the weights (13 GiB, about 9 minutes). Skip this step when the folder already has files.
   ```sh
   gcloud storage ls gs://$GCP_PROJECT_ID-models/qwen3.5-9b-fp8/
   gcloud run jobs execute weights-copy --wait \
     --update-env-vars HF_REPO=RedHatAI/Qwen3.5-9B-FP8-dynamic,TARGET_DIR=qwen3.5-9b-fp8
   ```
2. Build the image with Cloud Build (about 14 minutes). It pushes to the `models` repo. The tag must be the same as `image_tag` in `variables.tf`.
   ```sh
   gcloud builds submit deployments/llm-b-qwen35-9b-fastapi/image \
     --config=deployments/llm-b-qwen35-9b-fastapi/image/cloudbuild.yaml \
     --substitutions=_REGION=$GCP_REGION,_TAG=0.1.1 --region=$GCP_REGION
   ```
3. Apply. It makes the endpoint, the gateway and the CORS proxy.
   ```sh
   cd deployments/llm-b-qwen35-9b-fastapi && terraform init && terraform apply && cd ../..
   ```
4. Upload and deploy the model. It takes up to 45 minutes.
   ```sh
   ./scripts/vertex.py deploy deployments/llm-b-qwen35-9b-fastapi
   ```
5. Update the test UI (new tab, new panel code).
   ```sh
   ./scripts/ui-deploy.py
   ```

To change the code: raise `image_tag` in `variables.tf`, build with the new `_TAG`, run `./scripts/vertex.py undeploy deployments/llm-b-qwen35-9b-fastapi`, then `terraform apply`, then `vertex.py deploy`.
Do this once for a model deployed before 2026-11-20: it has container logs off, and the Slack alerts need them.

## Next plan after the proxy change (2026-11-23)

The shared file `infra/modules/cors-proxy/cors_proxy.py` changed (it maps the Runpod "no workers available" answer to 429). So the next plan of this deployment shows 1 in-place update of the proxy Cloud Run service `llm-b-qwen35-fastapi-proxy`: only its `args` change. This is expected. Nothing else changes, and the deployed model stays the same.

## Test

At 0 replicas the first call returns HTTP 429. The loop sends the call again every 30 s, for at most 30 minutes. It prints the time to the first `200`: this is the cold start.

```sh
cd deployments/llm-b-qwen35-9b-fastapi
BASE="https://$(terraform output -raw endpoint_dns)/v1/projects/$GCP_PROJECT_ID/locations/$GCP_REGION/endpoints/$(terraform output -raw endpoint_id)"
TOKEN=$(gcloud auth print-access-token)
start=$(date +%s)
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/out.json -w '%{http_code}' -X POST "$BASE/invoke/extract" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"text":"Ada Lovelace met Charles Babbage in London on 5 June 1833. Both later worked with the Royal Society."}')
  [ "$code" != 429 ] && break
  sleep 30
done
echo "$code after $(( $(date +%s) - start )) s"; python3 -m json.tool /tmp/out.json
```

Expected: `200` and valid JSON, for example `{"data": {"people": ["Ada Lovelace", "Charles Babbage"], "organizations": ["Royal Society"], ...}}`.

Own schema and `/generate`:

```sh
curl -s -X POST "$BASE/invoke/extract" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"Order 42: 3 red chairs, total 120 EUR.","schema":{"type":"object","properties":{"order_id":{"type":"integer"},"items":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"qty":{"type":"integer"}},"required":["name","qty"]}},"total":{"type":"number"},"currency":{"type":"string"}},"required":["order_id","items","total","currency"]}}'
curl -s -X POST "$BASE/invoke/generate" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"Say hello in 5 words.","max_tokens":32}'
```

## Cold start

Write the results here after each measured cold start. "Cold start" is the time from the first call at 0 replicas to the first `200` (the loop above prints it). Vertex AI writes no container log for this endpoint (see below), so there is no split into weights load and engine init.

| Date | Image tag | Event | Time | Notes |
|---|---|---|---|---|
| 2026-11-14 | 0.1.0 | First deploy (`vertex.py deploy`: model upload, node start, image pull, weights load, engine init) | 1398 s (23 min) | 1 replica up after the deploy. |
| 2026-11-14 | 0.1.0 | Scale up from 0 (first call 22:34:32 UTC, through the gateway, retry every 30 s) | failed: `429` for 1825 s, replicas stayed at 0 | Cause: no GPU stock. The deployed model status said `Machine type temporarily unavailable ... "g2-standard-8" ... "nvidia-l4"`. The project quota was fine. This is not a start-up time; measure again when a node is available. |
| 2026-11-16 | 0.1.0 | Scale up from 0 (first call 15:07:06 UTC, through the gateway, retry every 30 s) | **648 s (10.8 min)** to the first `200`; the scale-up began about 30 s before the first call | The deployed model status showed failed attempts first: `System error`, then `Machine type temporarily unavailable`, then `Model server never became ready`. Vertex AI retried by itself, and the next attempt answered. Plan for 10 to 30 min, or a failure when no L4 is free. |

## Check scale to zero

Send no requests for about 15 minutes (idle time 300 s plus the check interval). Then the replica count must be `0`: open the endpoint in the console (Vertex AI > Online prediction > Endpoints) and look at the replica chart. The next call must return `429` first.

Slack: after a cold start, the channel gets `🟢 LLM-B Qwen3.5 9B is ready`. After the scale down, it gets `⚪ LLM-B Qwen3.5 9B scaled to 0` (300 s idle time, then the shutdown). See [Scale notifications (Slack)](../../infra/README.md#scale-notifications-slack).

## Destroy

Undeploy first. Vertex AI does not delete an endpoint that has a deployed model.

```sh
./scripts/vertex.py undeploy deployments/llm-b-qwen35-9b-fastapi
cd deployments/llm-b-qwen35-9b-fastapi && terraform destroy
```

The weights and the image stay. Delete the image with `gcloud artifacts docker images delete $GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/models/llm-b-qwen35-9b-fastapi --delete-tags`.

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
