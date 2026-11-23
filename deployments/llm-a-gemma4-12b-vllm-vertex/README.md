# LLM-A on Vertex AI: Gemma 4 12B QAT (w4a16) on stock vLLM, 1 L4

First deployment of the module `infra/modules/model` with `local.platforms = ["vertex"]` (see `infra/README.md`, section "Module: model (platforms)"). Design: `docs/specs/2026-11-22-multi-platform-design.md`.

- Model `google/gemma-4-12B-it-qat-w4a16-ct`, served as `gemma-4-12b` by `vllm/vllm-openai:v0.33.0` (through the `dockerhub` proxy repo of `infra/core`).
- Private Vertex AI endpoint in `us-central1`: `g2-standard-12`, 1 `NVIDIA_L4`. It scales to zero (max 1 replica). A replica costs about $1.34 per hour.
- Weights: `gs://<project_id>-models/gemma-4-12b-it-qat-w4a16/`. Route: `/v1/chat/completions` through `:rawPredict`.
- Public API Gateway `llm-a-gemma4-vertex` checks `x-api-key`. A request without a key never starts a replica. Behind it, the private Cloud Run service `llm-a-gemma4-vertex-proxy` (made by the module) forwards the POST to Vertex AI and adds CORS headers to every answer, also to the 429. It answers `OPTIONS` too.

## Deploy

Do `infra/core` first (see `infra/README.md`). Run the commands from the repo root.

0. Check the weights folder and the L4 quota. Fix every FAIL. The weights check fails until step 1 is done.
   ```sh
   ./scripts/preflight.py --weights gemma-4-12b-it-qat-w4a16 --l4
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
   ./scripts/deploy.py deploy deployments/llm-a-gemma4-12b-vllm-vertex
   ./scripts/deploy.py status deployments/llm-a-gemma4-12b-vllm-vertex   # vertex: deployed
   ```
4. Turn on streaming, then update the UI.
   ```sh
   ./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm-vertex
   ./scripts/ui-deploy.py
   ```

To change the image, the args or the machine: run `./scripts/deploy.py undeploy deployments/llm-a-gemma4-12b-vllm-vertex`, then `terraform apply`, then `./scripts/deploy.py deploy deployments/llm-a-gemma4-12b-vllm-vertex`.
Do this once for a model deployed before 2026-11-20: it has container logs off, and the Slack alerts need them.

## Test UI and platforms (2026-11-23)

The `ui` output lists the platforms of this model (`platforms = module.model.ui_platforms`), and its `base_url` is the default platform path `<gateway>/vertex`. Apply this change only after the first plan below is applied, because the UI then calls `/vertex/v1/chat/completions`.

1. Run `terraform plan`. Expect only a change of the `ui` output, and no resource change.
2. Run `terraform apply`, then `./scripts/ui-deploy.py` (a full build, because `ui/` changed).
3. Open the UI. The LLM-A tab has no platform picker yet (1 platform), and its heading shows `Vertex AI`. The picker shows after a second platform (phase 3, Runpod).

## First plan after the move to the model module (2026-11-22)

The resources moved from `vertex-model`, `gateway.tf` and `cors_proxy.tf` into `infra/modules/model` (`moved.tf`). Run a plan before the first apply after this change:

```sh
cd deployments/llm-a-gemma4-12b-vllm-vertex && terraform init && terraform plan
```

Expected:

- 8 moves (`has moved to`): the endpoint, its service account and bucket IAM member, the CORS proxy module, the gateway service account, the API config, the gateway, and `module.scale_alerts` to `module.scale_alerts[0]`. Inside the proxy module, `google_project_iam_member.predict` also moves to `predict[0]`.
- 1 new API config (the `/vertex/...` path, `APPEND_PATH_TO_ADDRESS`), and the old API config destroyed after it.
- In-place updates: the gateway (`api_config`) and the proxy Cloud Run service (env `TARGETS`, `DEFAULT` and `TIMEOUT` replace `TARGET`, and the new `cors_proxy.py` in the args).
- No replace and no destroy of `google_vertex_ai_endpoint`, `google_api_gateway_gateway` or a service account.

Warning: if the plan shows anything else, do not apply. A replaced endpoint gets a new ID, and a replaced gateway gets a new URL.

After the apply, run `./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm-vertex` (it does nothing when the gateway still streams). Then do the test below on both paths. The deployed model does not change: the new flag order goes to Vertex AI only after the next `undeploy` and `deploy`.

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

The platform path gives the same answer. Change the URL in the loop to `"$GW/vertex/v1/chat/completions"`. The old path `/v1/chat/completions` goes to the first platform in `local.platforms`.

**Not verified:** the gateway sends a Google ID token, and Vertex AI may accept only access tokens. If this call returns `401` or `403` with `UNAUTHENTICATED` or `PERMISSION_DENIED`, put a small token proxy on Cloud Run between the gateway and the endpoint. Result: not tested yet.

CORS check (the answer must be `204` with `access-control-allow-origin`):

```sh
curl -si -X OPTIONS "$GW/v1/chat/completions" -H "Origin: https://storage.googleapis.com" \
  -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: content-type,x-api-key"
```

## Check scale to zero

Send no requests for about 15 minutes. Then the replica count must be `0`: open the endpoint in the console (Vertex AI > Online prediction > Endpoints) and look at the replica chart.

Slack: after a cold start, the channel gets `🟢 LLM-A Gemma 4 12B is ready`. After the scale down, it gets `⚪ LLM-A Gemma 4 12B scaled to 0` (300 s idle time, then the shutdown). See [Scale notifications (Slack)](../../infra/README.md#scale-notifications-slack).

## Destroy

Undeploy first. Vertex AI does not delete an endpoint that has a deployed model.

```sh
./scripts/deploy.py undeploy deployments/llm-a-gemma4-12b-vllm-vertex
cd deployments/llm-a-gemma4-12b-vllm-vertex && terraform destroy
```

The weights stay in the bucket. To remove the gateway API too, remove `llm-a-gemma4-vertex` from `local.gateway_apis` in `infra/core/gateways.tf` and apply `infra/core/`.
