# LLM-A on Vertex AI: Gemma 4 12B QAT (w4a16) on stock vLLM, 1 L4

First deployment of the module `infra/modules/vertex-model` (see `infra/README.md`, section "Module: vertex-model").

- Model `google/gemma-4-12B-it-qat-w4a16-ct`, served as `gemma-4-12b` by `vllm/vllm-openai:v0.33.0` (through the `dockerhub` proxy repo of `infra/core`).
- Private Vertex AI endpoint in `us-central1`: `g2-standard-12`, 1 `NVIDIA_L4`. It scales to zero (max 1 replica). A replica costs about $1.34 per hour.
- Weights: `gs://<project_id>-models/gemma-4-12b-it-qat-w4a16/`. Route: `/v1/chat/completions` through `:rawPredict`.
- Public API Gateway `llm-a-gemma4-vertex` checks `x-api-key`. A request without a key never starts a replica. Behind it, the private Cloud Run service `llm-a-gemma4-vertex-proxy` (`cors_proxy.tf`) forwards the POST to Vertex AI and adds CORS headers to every answer, also to the 429. It answers `OPTIONS` too.

## Deploy

Do `infra/core` first (see `infra/README.md`). Run the commands from the repo root.

0. Check the weights folder and the L4 quota. Fix every FAIL. The weights check fails until step 1 is done.
   ```sh
   direnv exec . ./scripts/preflight.py --weights gemma-4-12b-it-qat-w4a16 --l4
   ```
1. Copy the weights. Skip this step when the folder already has files.
   ```sh
   gcloud storage ls gs://$GCP_PROJECT_ID-models/gemma-4-12b-it-qat-w4a16/
   gcloud run jobs execute weights-copy --wait \
     --update-env-vars HF_REPO=google/gemma-4-12B-it-qat-w4a16-ct,TARGET_DIR=gemma-4-12b-it-qat-w4a16
   ```
2. Apply.
   ```sh
   cd deployments/llm-a-gemma4-12b-vllm-vertex && terraform init && terraform apply && cd ../..
   ```
3. Fill the image cache, upload and deploy the model. The script fills the cache first and stops if the answer is not `200`. It takes up to 45 minutes.
   ```sh
   ./scripts/vertex.py deploy deployments/llm-a-gemma4-12b-vllm-vertex
   ```
4. Turn on streaming, then update the UI.
   ```sh
   ./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm-vertex
   ./scripts/ui-deploy.py
   ```

To change the image, the args or the machine: run `./scripts/vertex.py undeploy deployments/llm-a-gemma4-12b-vllm-vertex`, then `terraform apply`, then `vertex.py deploy`.

## Test

At 0 replicas the first call returns HTTP 429. The loop sends the call again every 30 s, for at most 30 minutes.

```sh
cd deployments/llm-a-gemma4-12b-vllm-vertex
GW=$(terraform output -raw gateway_url)
KEY=$(cd ../../infra/core && terraform output -raw api_key)
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/out.json -w '%{http_code}' -X POST "$GW/v1/chat/completions" \
    -H "x-api-key: $KEY" -H "Content-Type: application/json" \
    -d '{"model":"gemma-4-12b","messages":[{"role":"user","content":"Say hello in 5 words."}],"max_tokens":32}')
  [ "$code" != 429 ] && break
  sleep 30
done
echo "$code"; cat /tmp/out.json
```

Expected: `200` and a short text. A call without `x-api-key` must return `401`.

**Not verified:** the gateway sends a Google ID token, and Vertex AI may accept only access tokens. If this call returns `401` or `403` with `UNAUTHENTICATED` or `PERMISSION_DENIED`, put a small token proxy on Cloud Run between the gateway and the endpoint. Result: not tested yet.

CORS check (the answer must be `204` with `access-control-allow-origin`):

```sh
curl -si -X OPTIONS "$GW/v1/chat/completions" -H "Origin: https://storage.googleapis.com" \
  -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: content-type,x-api-key"
```

## Check scale to zero

Send no requests for about 15 minutes. Then the replica count must be `0`: open the endpoint in the console (Vertex AI > Online prediction > Endpoints) and look at the replica chart.

## Destroy

Undeploy first. Vertex AI does not delete an endpoint that has a deployed model.

```sh
./scripts/vertex.py undeploy deployments/llm-a-gemma4-12b-vllm-vertex
cd deployments/llm-a-gemma4-12b-vllm-vertex && terraform destroy
```

The weights stay in the bucket. To remove the gateway API too, remove `llm-a-gemma4-vertex` from `local.gateway_apis` in `infra/core/gateways.tf` and apply `infra/core/`.
