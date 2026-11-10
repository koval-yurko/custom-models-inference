# LLM-A on Vertex AI: Gemma 4 12B QAT (w4a16) on stock vLLM, 1 L4

This is the Vertex AI version of `deployments/llm-a-gemma4-12b-vllm` (Cloud Run). It is the first deployment of the module `infra/modules/vertex-model` (see `infra/README.md`, section "Module: vertex-model").

- Model: `google/gemma-4-12B-it-qat-w4a16-ct`, served as `gemma-4-12b` by the stock image `vllm/vllm-openai:v0.33.0`. The image comes through the `infra/core` Docker Hub proxy (`dockerhub` repo), because Vertex AI pulls only from Artifact Registry.
- Dedicated Vertex AI endpoint `llm-a-gemma4-12b-vllm-vertex` in `europe-west4`: `g2-standard-8`, 1 `NVIDIA_L4`, 16384 MB shared memory, deployment timeout 1800 s.
- Weights: the same folder as the Cloud Run version, `gs://<project_id>-models/gemma-4-12b-it-qat-w4a16/`. vLLM streams them from `$AIP_STORAGE_URI` with `--load-format=runai_streamer`.
- Routes: health `/health`. Predict `/v1/chat/completions` through `:rawPredict`.
- Scales to zero (min 0, max 1 replica, idle time 300 s). The endpoint is private: a direct caller needs `aiplatform.endpoints.predict` on the project (for example `roles/aiplatform.user`).
- A public API Gateway (`gateway.tf`, ID `llm-a-gemma4-vertex`) checks the shared `x-api-key` before it calls the endpoint. Only `POST /v1/chat/completions` goes through. Its service account has `roles/aiplatform.user` on the project. **Not verified:** the gateway sends a Google ID token, and Vertex AI may accept only access tokens. See [Gateway: not verified](#gateway-not-verified).
- Billing is per node-hour while a replica runs (L4 about $1 per hour). Each test session bills at least 10 minutes (`min_scaleup_period` plus `idle_scaledown_period`).

## Prerequisites

1. Set up `.env` and direnv as in `infra/README.md`.
2. Apply `infra/core`. It turns on the Vertex AI API, creates the `dockerhub` repo, and creates the gateway API `llm-a-gemma4-vertex` (`local.gateway_apis` in `gateways.tf`). For that API, it also creates a placeholder config and the enabled managed service, and adds the service to the shared API key.
3. Check the Vertex AI L4 quota. See `infra/README.md`, section "Vertex AI GPU quota". The value for `europe-west4` must be 1 or more.
4. Copy the weights. If the Cloud Run version already runs, the folder is there. Check it:
   ```sh
   gcloud storage ls -l gs://$GCP_PROJECT_ID-models/gemma-4-12b-it-qat-w4a16/
   ```
   If it is empty, run the job:
   ```sh
   gcloud run jobs execute weights-copy --wait \
     --update-env-vars HF_REPO=google/gemma-4-12B-it-qat-w4a16-ct,TARGET_DIR=gemma-4-12b-it-qat-w4a16
   ```
5. Create the HCP workspace and its variables: `./scripts/hcp-sync.py --dry-run`, then `./scripts/hcp-sync.py`.

## Apply and deploy

1. Apply. HCP Terraform creates the endpoint, the model service account and its read access to the weights bucket, and the gateway with its service account.
   ```sh
   cd deployments/llm-a-gemma4-12b-vllm-vertex
   direnv exec . terraform init
   direnv exec . terraform apply
   ```
2. Upload and deploy the model. The script waits for both operations. The deploy can take 30 minutes.
   ```sh
   direnv exec . ../../infra/modules/vertex-model/vertex.sh deploy
   ```

To change the image, the args or the machine: run `vertex.sh undeploy`, then `terraform apply`, then `vertex.sh deploy`.

Streaming through the gateway (SSE, `"stream": true`) needs the post-apply script. See `infra/README.md`, section "Streaming":

```sh
./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm-vertex
```

## Test call (direct, with an access token)

The deploy starts with 1 replica. When the endpoint is at 0 replicas, the first call returns HTTP 429. The loop below sends the call again every 30 s, for at most 30 minutes.

```sh
DNS=$(direnv exec . terraform output -raw endpoint_dns)
EP=$(direnv exec . terraform output -raw endpoint_id)
URL="https://$DNS/v1/projects/$GCP_PROJECT_ID/locations/europe-west4/endpoints/$EP:rawPredict"
cat > /tmp/body.json <<'JSON'
{"model":"gemma-4-12b","messages":[{"role":"user","content":"Say hello in 5 words."}],"max_tokens":32}
JSON
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/out.json -w '%{http_code}' -X POST "$URL" \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" -d @/tmp/body.json)
  [ "$code" != 429 ] && break
  sleep 30
done
echo "$code"; jq -r '.choices[0].message.content' /tmp/out.json
```

Expected: `200` and a short text.

## Test call through the gateway (API key)

Use the same 429 retry loop. Only the URL and the auth header change:

```sh
GW=$(direnv exec . terraform output -raw gateway_url)
KEY=$(cd ../../infra/core && direnv exec . terraform output -raw api_key)
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/out.json -w '%{http_code}' -X POST "$GW/v1/chat/completions" \
    -H "x-api-key: $KEY" -H "Content-Type: application/json" -d @/tmp/body.json)
  [ "$code" != 429 ] && break
  sleep 30
done
echo "$code"; cat /tmp/out.json
```

Expected: `200` and a short text. A call without `x-api-key` must return `401` from the gateway.

Streaming (only after `scripts/gateway-streaming.py`, and only when the replica runs). Ask for a long answer, so that the tokens come over some seconds:

```sh
curl -sS -N -X POST "$GW/v1/chat/completions" -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d '{"model":"gemma-4-12b","messages":[{"role":"user","content":"Write 30 numbered sentences about the sea."}],"max_tokens":1024,"stream":true}' \
  -o /tmp/stream.txt -w 'first byte: %{time_starttransfer}s, total: %{time_total}s\n'
```

Streaming works when the first byte comes after about 1 s and the total after many seconds. Without streaming, the first byte and the total are almost the same. Not checked: SSE through `:rawPredict`.

### Gateway: not verified

API Gateway calls the backend with a Google-signed ID token of its service account. Google APIs, and so Vertex AI, usually expect an OAuth access token. Write the result of the first gateway call here:

| Result | Meaning | Next step |
|---|---|---|
| `200` with text | Vertex AI accepts the ID token | Done. Remove the "not verified" notes. |
| `429` until the loop ends | Cold start longer than 30 min | Check the endpoint logs |
| `401` or `403` from Vertex AI (JSON with `"status": "UNAUTHENTICATED"` or `PERMISSION_DENIED`) | Vertex AI rejects the ID token | Put a small token proxy on Cloud Run between the gateway and the endpoint. The proxy calls Vertex AI with an access token of its own service account. |

Result: not tested yet.

### Full OpenAI API through :invoke (option)

`:rawPredict` reaches only `/v1/chat/completions`. To reach every route (`/v1/models`, `/v1/completions` and others), set `invoke_routes = true` and remove `predict_route` in `main.tf`. Then run `undeploy`, `apply` and `deploy`. The URL becomes `https://$DNS/v1/projects/$GCP_PROJECT_ID/locations/europe-west4/endpoints/$EP/invoke/v1/chat/completions`. With this option, `:predict` and `:rawPredict` are off. Streamed (SSE) responses through `:invoke` are not checked. The gateway backend in `gateway.tf` then needs the `/invoke` URL and more paths.

## Measure the cold start

1. Wait until the endpoint has 0 replicas (see the next section).
2. Run the test call loop with `time` in front of it, or note the clock time before and after.
3. The cold start is the time from the first 429 to the first 200.

Write the result here:

| Date | vLLM | Weights load | Cold start (first 429 to first 200) |
|---|---|---|---|
| not measured yet | v0.33.0 | runai_streamer from GCS | — |

The endpoint logs show the parts: in the console, open Vertex AI > Online prediction > Endpoints > the endpoint > Logs. Look for `Loading weights took ... seconds` and `Application startup complete`.

## Check scale to zero

Send no requests for about 15 minutes (`min_scaleup_period` 300 s plus `idle_scaledown_period` 300 s, plus a margin). Then read the replica count:

```sh
START=$(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ)   # macOS; on Linux: date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ
END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl -sS -G "https://monitoring.googleapis.com/v3/projects/$GCP_PROJECT_ID/timeSeries" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  --data-urlencode "filter=metric.type=\"aiplatform.googleapis.com/prediction/online/replicas\" AND resource.labels.endpoint_id=\"$EP\"" \
  --data-urlencode "interval.startTime=$START" \
  --data-urlencode "interval.endTime=$END"
```

The newest points must show `0` (or the series has no recent points). You can also open the endpoint in the console and look at the replica count chart.

## Destroy

Undeploy first. Vertex AI does not delete an endpoint that has a deployed model.

```sh
direnv exec . ../../infra/modules/vertex-model/vertex.sh undeploy
direnv exec . terraform destroy
```

The weights stay in the bucket, because the Cloud Run version uses the same folder.

To remove the gateway API too, remove `llm-a-gemma4-vertex` from `local.gateway_apis` in `infra/core/gateways.tf` after the destroy. Then apply `infra/core/`.

## Not checked yet (first real run)

These items come from `infra/README.md` and from this deployment. Write the result here after the first deploy.

1. vLLM `runai_streamer` reads `gs://` in `v0.33.0`. If it fails, see the fallback in `infra/README.md` (section "Module: vertex-model", "Weights flow").
2. Vertex AI expands `$(AIP_STORAGE_URI)` in `args`, and the service account can read that URI.
3. The `/invoke/<path>` URL form (only with `invoke_routes = true`).
4. The L4 quota for Vertex AI prediction in `europe-west4`.
5. Vertex AI accepts the ID token of the gateway (see [Gateway: not verified](#gateway-not-verified)).
