# LLM-A: Gemma 4 12B QAT (w4a16) on stock vLLM, 1 L4

Gemma 4 12B instruct, QAT 4-bit checkpoint `google/gemma-4-12B-it-qat-w4a16-ct` (10.3 GB, Apache 2.0), served by the stock image `vllm/vllm-openai:v0.33.0`. OpenAI-compatible API (`/v1/chat/completions`, `/v1/models`).

- Cloud Run service `llm-a-gemma4-12b-vllm` in `europe-west4`: 1 NVIDIA L4, 8 vCPU, 32 GiB, zonal redundancy off.
- Weights come from the bucket `<project_id>-models`, mounted read-only at `/models`. Nothing is downloaded at start (`HF_HUB_OFFLINE=1`).
- Scales to zero (min 0, max 1). Private: only `INVOKER_EMAIL` can call it.
- Billing is per instance while it runs (about $1 per hour for an L4 instance), and 0 when it has no instances.

Why not 26B A4B: Google publishes no QAT w4a16 checkpoint for Gemma 4 26B A4B (only E2B, E4B, 12B and 31B). See `docs/research/02-open-weight-models.md`, section A.

## Prerequisites

1. Set up `.env` and direnv as in `infra/bootstrap/README.md` (section "State (HCP Terraform)").
2. Apply `infra/bootstrap` (it creates the weights bucket, the `hf-token` secret with the value of `HF_TOKEN` from `.env`, and the `weights-copy` job).
3. Check the L4 quota in the region. Cloud Run needs the "without zonal redundancy" L4 quota to be 1 or more:
   ```sh
   gcloud beta quotas info list --service=run.googleapis.com \
     --filter="quotaId~L4" --format="table(quotaId,dimensionsInfos[].details.value)"
   ```
   If the value for `europe-west4` is 0, ask for more in the console: IAM & Admin > Quotas, filter "Cloud Run Admin API" and "L4".
4. Put `GCP_PROJECT_ID` and `INVOKER_EMAIL` in `.env`. `.envrc` maps them to Terraform variables.

## Copy the weights (one time)

```sh
gcloud run jobs execute weights-copy --wait \
  --update-env-vars HF_REPO=google/gemma-4-12B-it-qat-w4a16-ct,TARGET_DIR=gemma-4-12b-it-qat-w4a16
gcloud storage ls -l gs://$GCP_PROJECT_ID-models/gemma-4-12b-it-qat-w4a16/
```

Expected: `model.safetensors` (about 10.3 GB), `config.json`, `tokenizer.json` and the other repo files.

## Apply

```sh
cd deployments/llm-a-gemma4-12b-vllm
terraform init
terraform apply
```

The apply waits for the first instance to become ready, so it can take 10 minutes or more.

## Test call

The token comes from the service account in `.env`. The service account must be in `invokers` (the module grants `run.invoker` only to the listed members). If the call returns 403, add `serviceAccount:<email>` to `invokers`.

```sh
URL=$(terraform output -raw url)
TOKEN=$(gcloud auth print-identity-token --audiences="$URL")
curl -sS "$URL/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"gemma-4-12b","messages":[{"role":"user","content":"Say hello in 5 words."}],"max_tokens":32}'
```

Expected: JSON with `choices[0].message.content`.

## Measure the cold start

Wait until the service has 0 instances (see the next section). Then:

```sh
time curl -sS -o /dev/null -w '%{http_code}\n' "$URL/v1/models" -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences="$URL")"
```

Write the result here:

| Date | vLLM | Weights load | Cold start (first `/v1/models` 200) |
|---|---|---|---|
| not measured yet | v0.33.0 | GCS FUSE | — |

The service logs show the parts: container start, `Loading weights took ... seconds`, and `Application startup complete`.

## Check scale to zero

Send no requests for about 15 minutes. Then use the same Monitoring query as in `deployments/tts-a-kokoro-cpu/README.md`, with `resource.labels.service_name="llm-a-gemma4-12b-vllm"`. The newest points must show `0`.

## Fallback

If the 4-bit quality is too low, copy another model with the job and change `local.model_dir`, `--served-model-name` and `name` in `main.tf`. Candidates: `gpt-oss-20b` or `Qwen3.5-9B` (see `docs/research/02-open-weight-models.md`).

## Destroy

```sh
terraform destroy
```

The weights stay in the bucket. Delete them with `gcloud storage rm -r gs://$GCP_PROJECT_ID-models/gemma-4-12b-it-qat-w4a16/`.
