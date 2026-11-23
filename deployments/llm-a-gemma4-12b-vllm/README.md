# LLM-A on Vertex AI and Runpod: Gemma 4 12B QAT (w4a16) on stock vLLM

First deployment of the module `infra/modules/model`. It has `local.platforms = ["vertex", "runpod"]` (see `infra/README.md`, section "Module: model (platforms)"). Design: `docs/specs/2026-11-22-multi-platform-design.md`.

- Model `google/gemma-4-12B-it-qat-w4a16-ct`, served as `gemma-4-12b` by `vllm/vllm-openai:v0.33.0` (through the `dockerhub` proxy repo of `infra/core`).
- Private Vertex AI endpoint in `us-central1`: `g2-standard-12`, 1 `NVIDIA_L4`. It scales to zero (max 1 replica). A replica costs about $1.34 per hour.
- Weights: `gs://<project_id>-models/gemma-4-12b-it-qat-w4a16/`. Route: `/v1/chat/completions` through `:rawPredict`.
- Runpod (since 2026-11-23): 1 load balancing endpoint `llm-a-gemma4-12b-vllm`, pool `AMPERE_24` (L4, A5000 or 3090), 0 to 1 worker, 300 s idle time. vLLM downloads the weights from Hugging Face at start (commit `1d2c2d7f`). Path: `/runpod/v1/chat/completions`.
- Public API Gateway `llm-a-gemma4` checks `x-api-key`. A request without a key never starts a replica. Behind it, the private Cloud Run service `llm-a-gemma4-proxy` (made by the module) forwards the POST to the platform (Vertex AI or Runpod) and adds CORS headers to every answer, also to the 429. It answers `OPTIONS` too.

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
   cd deployments/llm-a-gemma4-12b-vllm && terraform init && terraform apply && cd ../..
   ```
3. Fill the image cache, upload and deploy the model. The script fills the cache first and stops if the answer is not `200`. It takes up to 45 minutes.
   ```sh
   ./scripts/deploy.py deploy deployments/llm-a-gemma4-12b-vllm
   ./scripts/deploy.py status deployments/llm-a-gemma4-12b-vllm   # vertex: deployed
   ```
4. Turn on streaming, then update the UI.
   ```sh
   ./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm
   ./scripts/ui-deploy.py
   ```

To change the image, the args or the machine: run `./scripts/deploy.py undeploy deployments/llm-a-gemma4-12b-vllm`, then `terraform apply`, then `./scripts/deploy.py deploy deployments/llm-a-gemma4-12b-vllm`.
Do this once for a model deployed before 2026-11-20: it has container logs off, and the Slack alerts need them.

## Rename (2026-11-23)

The deployment had the name `llm-a-gemma4-12b-vllm-vertex`. It has several platforms now, so the `-vertex` suffix is gone from 3 names:

| Old | New |
|---|---|
| Folder and HCP workspace `custom-models-llm-a-gemma4-12b-vllm-vertex` | `custom-models-llm-a-gemma4-12b-vllm` |
| Vertex AI name `llm-a-gemma4-12b-vllm-vertex` | `llm-a-gemma4-12b-vllm` |
| Gateway ID `llm-a-gemma4-vertex` (CORS proxy `llm-a-gemma4-vertex-proxy`) | `llm-a-gemma4` (CORS proxy `llm-a-gemma4-proxy`) |

The old deployment was destroyed on 2026-11-23 (`deploy.py undeploy`, then `terraform destroy` in the old workspace: 17 resources on Vertex AI, Cloud Run and Runpod). The new names start from an empty state. Run the commands from the repo root.

1. Make the new HCP workspace.
   ```sh
   ./scripts/hcp-sync.py --dry-run && ./scripts/hcp-sync.py
   ```
2. Apply `infra/core`. Expect: create the API `llm-a-gemma4` (API, placeholder config, service), delete the old API `llm-a-gemma4-vertex`, and an update in place of the API key `models-gateways`.
   ```sh
   cd infra/core && terraform plan && terraform apply && cd ../..
   ```
3. Do the steps in [Deploy](#deploy) from step 2. The gateway URL is new, so do step 4 (streaming and UI) too. The UI tab ID is now `llm-a-gemma4`, so an old link `#/llm-a-gemma4-vertex` opens the first tab.
4. Delete the empty HCP workspace `custom-models-llm-a-gemma4-12b-vllm-vertex` in the HCP UI.

## Test UI and platforms (2026-11-23)

The `ui` output lists the platforms of this model (`platforms = module.model.ui_platforms`), and its `base_url` is the default platform path `<gateway>/vertex`. Apply this change only after the first plan below is applied, because the UI then calls `/vertex/v1/chat/completions`.

1. Run `terraform plan`. Expect only a change of the `ui` output, and no resource change.
2. Run `terraform apply`, then `./scripts/ui-deploy.py` (a full build, because `ui/` changed).
3. Open the UI. The LLM-A tab has a platform picker with `Vertex AI` and `Runpod` after the Runpod apply below. The picker shows only the deployed platforms. Before it, the tab has no picker (1 platform).

## Runpod (2026-11-23)

Do these steps after the first plan below and the "Test UI and platforms" steps. One-time setup: see [Runpod setup (once)](../../infra/README.md#runpod-setup-once) (account, `RUNPOD_API_KEY`, `./scripts/hcp-sync.py`, `infra/core` apply).

1. Run a plan.
   ```sh
   cd deployments/llm-a-gemma4-12b-vllm && terraform init && terraform plan
   ```
   Expected:
   - Create `module.model.module.runpod[0].runpod_template.this` and `runpod_serverless_endpoint.this`.
   - Create the `secretAccessor` member of the proxy service account on the secret `runpod-api-key`.
   - Update the proxy Cloud Run service in place: a new `TARGETS` value (with `runpod`), the secret env var `RUNPOD_API_KEY`, and new `args` (the new `cors_proxy.py` with the Runpod 429 mapping).
   - 1 new API config (the `/runpod/...` path), the old API config destroyed after it, and the gateway updated in place.
   - The `ui` output gets a second platform.
   - No replace and no destroy of `google_vertex_ai_endpoint`, `google_api_gateway_gateway` or a service account.

   Warning: if the plan shows anything else, do not apply.
2. Apply, then run the post-apply steps.
   ```sh
   terraform apply && cd ../..
   ./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm
   ./scripts/deploy.py status deployments/llm-a-gemma4-12b-vllm   # vertex: deployed, runpod: deployed
   ./scripts/ui-deploy.py
   ```
3. Warning: a call starts a Runpod GPU worker. Runpod bills it per second until the 300 s idle time ends. Do the [Test](#test) with the URL `"$GW/runpod/v1/chat/completions"`. At 0 workers the proxy changes the Runpod answer "no workers available" to `429`, so the same loop works.
4. Fill in this table at the first cold call. Read the raw Runpod answer in the proxy log (the line starts with `runpod cold:`):
   ```sh
   gcloud logging read 'resource.labels.service_name="llm-a-gemma4-proxy" AND textPayload:"runpod cold:"' --limit 5 --format='value(textPayload)'
   ```
   If the loop gets a status other than `429` or `200` at once, send the answer to the agent. Only `cold_answer` in `infra/modules/cors-proxy/cors_proxy.py` changes.

| Item | Value |
|---|---|
| Raw status and body at 0 workers | No error. Runpod held the first request until the worker was ready, and the proxy wrote no `runpod cold:` line (2026-11-23) |
| Time from the first call to the first `200` | 182 s, 1 try, no `429` (cold start with the weights download from Hugging Face, 2026-11-23) |
| Time of a warm call (`max_tokens` 32) | 1 s (2026-11-23) |
| Second cold call, from the test UI (2026-11-23 08:58 UTC) | 200 after 214.8 s, no retry needed; the UI showed the wait line the whole time |
| GPU type that Runpod gave | NVIDIA RTX A5000 in CA-MTL-1 (`GET https://api.runpod.io/v2/serverless/<id>/workers`) |

The first cold call did not get a `429`: Runpod holds a request at 0 workers (182 s here). The 429 mapping in the proxy stays as a guard for a "no workers available" answer. The gateway deadline is 300 s, so a cold start that takes longer than about 5 minutes gets a gateway timeout. Then send the call again: the worker is still starting.

## Next plan after the vertex-model merge (2026-11-24)

The code of `infra/modules/vertex-model` moved into `infra/modules/platform-vertex` (its `moved.tf`). So the next plan shows 3 moves, from `module.model.module.vertex[0].module.engine.<resource>` to `module.model.module.vertex[0].<resource>`: the endpoint, its service account and the bucket IAM member. Nothing is added, changed or destroyed for them. If the plan shows a replace of `google_vertex_ai_endpoint`, stop and check `moved.tf` against `terraform state list`.

## First plan after the move to the model module (2026-11-22)

The resources moved from `vertex-model`, `gateway.tf` and `cors_proxy.tf` into `infra/modules/model` (`moved.tf`). Run a plan before the first apply after this change:

```sh
cd deployments/llm-a-gemma4-12b-vllm && terraform init && terraform plan
```

Expected:

- 8 moves (`has moved to`): the endpoint, its service account and bucket IAM member, the CORS proxy module, the gateway service account, the API config, the gateway, and `module.scale_alerts` to `module.scale_alerts[0]`. Inside the proxy module, `google_project_iam_member.predict` also moves to `predict[0]`.
- 1 new API config (the `/vertex/...` path, `APPEND_PATH_TO_ADDRESS`), and the old API config destroyed after it.
- In-place updates: the gateway (`api_config`) and the proxy Cloud Run service (env `TARGETS`, `DEFAULT` and `TIMEOUT` replace `TARGET`, and the new `cors_proxy.py` in the args).
- No replace and no destroy of `google_vertex_ai_endpoint`, `google_api_gateway_gateway` or a service account.

Warning: if the plan shows anything else, do not apply. A replaced endpoint gets a new ID, and a replaced gateway gets a new URL.

After the apply, run `./scripts/gateway-streaming.py deployments/llm-a-gemma4-12b-vllm` (it does nothing when the gateway still streams). Then do the test below on both paths. The deployed model does not change: the new flag order goes to Vertex AI only after the next `undeploy` and `deploy`.

## Test

At 0 replicas the first call returns HTTP 429. The loop sends the call again every 30 s, for at most 30 minutes.

```sh
cd deployments/llm-a-gemma4-12b-vllm
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
./scripts/deploy.py undeploy deployments/llm-a-gemma4-12b-vllm
cd deployments/llm-a-gemma4-12b-vllm && terraform destroy
```

The weights stay in the bucket. To remove the gateway API too, remove `llm-a-gemma4` from `local.gateway_apis` in `infra/core/gateways.tf` and apply `infra/core/`.
