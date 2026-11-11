# Infrastructure

`infra/` has 3 folders and this README:

| Folder | Content |
|---|---|
| `core/` | One Terraform root with one apply. It prepares one GCP project for all deployments under `deployments/`. |
| `modules/model-service/` | The Cloud Run module. Each Cloud Run deployment calls it. |
| `modules/vertex-model/` | The Vertex AI module. Each Vertex AI deployment calls it. |

Contents:

1. [What core creates](#what-core-creates)
2. [First setup](#first-setup)
3. [HCP Terraform (state and runs)](#hcp-terraform-state-and-runs)
4. [Apply](#apply)
5. [Copy model weights](#copy-model-weights)
6. [API Gateway and API keys](#api-gateway-and-api-keys)
7. [Module: model-service](#module-model-service)
8. [Module: vertex-model](#module-vertex-model)
9. [Test UI](#test-ui)
10. [Tests](#tests)

## What core creates

- The APIs: run, artifactregistry, cloudbuild, secretmanager, storage, compute, billingbudgets, iam, cloudresourcemanager, serviceusage, apigateway, servicemanagement, servicecontrol, apikeys, aiplatform (Vertex AI).
- The bucket `<project_id>-models` for model weights.
- The Artifact Registry Docker repo `models` for custom images.
- The Artifact Registry remote repo `ghcr`, a proxy for `ghcr.io`. Cloud Run cannot pull from `ghcr.io` directly.
- The Artifact Registry remote repo `dockerhub`, a proxy for Docker Hub. Vertex AI pulls images only from Artifact Registry.
- A monthly billing budget with email alerts at 50%, 90% and 100%. A budget does not stop spend.
- The Secret Manager secret `hf-token` and its value, taken from `HF_TOKEN` in `.env`. The value is write-only: it is not in the Terraform state. To rotate it, change `HF_TOKEN` and raise `secret_data_wo_version` in `weights_copy.tf`.
- The Cloud Run job `weights-copy` and its service account. The job copies 1 Hugging Face repo into `<project_id>-models/<TARGET_DIR>/`. It can write to the weights bucket and read `hf-token`, and nothing more.
- One API Gateway API for each entry in `local.gateway_apis` (`gateways.tf`), and a placeholder API config. A managed service can be enabled only after its API has a config, so the placeholder comes first, then the enabled service, then the key. No gateway uses the placeholder.
- One API key for all gateways (`models-gateways`). The key works only for those gateway APIs.
- The bucket `<project_id>-ui` for the static test UI (`ui.tf`). Anyone can read a file in it (`roles/storage.legacyObjectReader`: no list, no write). See [Test UI](#test-ui).

All resources go in `europe-west4` by default. Set `GCP_REGION` in `.env` to change it.

| File in `core/` | Content |
|---|---|
| `main.tf` | APIs, buckets, Artifact Registry repos, budget |
| `weights_copy.tf` | `hf-token` secret and `weights-copy` job |
| `gateways.tf` | Gateway APIs and the shared API key |
| `ui.tf` | Public bucket of the test UI |

## First setup

1. Create the project and link it to a billing account.
2. Create a service account key (see `.env.example`). Put its path in `GOOGLE_APPLICATION_CREDENTIALS` in `.env`. Terraform and gcloud both use this key. `.envrc` sets `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE` to the same file and `CLOUDSDK_CONFIG` to the local `.gcloud/` folder, so gcloud never uses your global login or config. Do not run `gcloud auth login` for this project. Check: `gcloud auth print-access-token >/dev/null && echo ok`.
3. Turn on the 2 APIs that Terraform needs before it can turn on the others:
   ```sh
   gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com
   ```
4. Give the service account the Owner role on the project. Also give it Billing Account Costs Manager (or Billing Account Administrator) on the billing account.
5. Put `GCP_PROJECT_ID` and `BILLING_ACCOUNT` in `.env` (see `.env.example`). `.envrc` maps them to `TF_VAR_project_id` and `TF_VAR_billing_account`. Find the billing account ID with `gcloud billing accounts list`. There is no `terraform.tfvars` file.

## HCP Terraform (state and runs)

Terraform runs on HCP Terraform (remote execution). HCP stores the state, the variables and the Google credentials. Do this once:

1. Create an HCP Terraform organization and a project (for example `custom-models-inference`).
2. Copy `.env.example` to `.env` in the repo root and fill it in. Run `direnv allow` in the repo root. direnv then loads `.env` when you enter the folder. Run `direnv allow` again each time `.envrc` changes, for example after `git pull`. If you do not, direnv blocks `.envrc` and `terraform init` fails with `"organization" must be set`. Check it with `echo $TF_CLOUD_ORGANIZATION`. Without direnv, run `set -a; source .env; set +a` in each shell. `TF_TOKEN_app_terraform_io` replaces `terraform login`.
3. Sync `.env` to HCP. The script creates the workspaces in the project, sets remote execution, and writes the variables. It also writes the service account key as the sensitive variable `GOOGLE_CREDENTIALS`.
   ```sh
   ./scripts/hcp-sync.py --dry-run   # shows what it will do, no values
   ./scripts/hcp-sync.py
   ```
   Run the script again each time you change `.env`.
4. Run `terraform init` and `terraform apply` in each root. The plan and apply run on HCP. The terminal shows the output.

**The run does not use your `.env` or your gcloud login.** It uses the workspace variables from step 3. A local `.env` change has no effect until you run the script again.

**What the CLI uploads.** For `infra/core/`, the CLI uploads only the `infra/core/` folder. The deployments use the module in `infra/modules/`, so the CLI uploads the whole repo for them (the workspace working directory is `deployments/<name>`). `.terraformignore` keeps `.env`, key files and `.gcloud/` out of the upload. Do not remove it.

The workspace of `infra/core/` is `custom-models-bootstrap` (the old name, kept so that the state stays). Each root has its workspace name in `backend.tf`.

## Apply

```sh
cd infra/core
terraform init
terraform apply
```

Outputs: `weights_bucket`, `models_repo`, `ghcr_repo`, `dockerhub_repo`, `region`, `weights_copy_job`, `gateway_apis` and `api_key` (sensitive). Cloud Run deployments use `ghcr_repo`. Vertex AI deployments use `dockerhub_repo` for stock images, for example `<dockerhub_repo>/vllm/vllm-openai:v0.33.0`.

### Vertex AI GPU quota (check before the first Vertex AI deployment)

A Vertex AI endpoint with 1 `NVIDIA_L4` on `g2-standard-8` needs the quota "Custom model serving Nvidia L4 GPUs per region" in `europe-west4`. Prediction quota is separate from Compute Engine and Cloud Run GPU quota.

1. Apply `infra/core/` first. It turns on `aiplatform.googleapis.com`.
2. Open the console: IAM & Admin > Quotas & System Limits. Filter for `Service: Vertex AI API` and `L4`. Read the value for `region: europe-west4`.
3. Or use the CLI. This needs the Cloud Quotas API (`gcloud services enable cloudquotas.googleapis.com`) and the gcloud `beta` component:
   ```sh
   gcloud beta quotas info list --service=aiplatform.googleapis.com --format=json \
     | jq -r '.[] | select(.quotaId | test("L4")) | .quotaId as $q | .dimensionsInfos[] | select(.dimensions.region == "europe-west4") | "\($q) \(.details.value)"'
   ```
4. If the value is 0, request 1 GPU on the same console page. Scale to zero reserves quota for `max_replica_count`.

## Copy model weights

Run the job 1 time for each model. Set the repo and the target folder for each execution:

```sh
gcloud run jobs execute weights-copy --wait \
  --update-env-vars HF_REPO=google/gemma-4-12B-it-qat-w4a16-ct,TARGET_DIR=gemma-4-12b-it-qat-w4a16
```

The job mounts the bucket with GCS FUSE at `/models` and runs `hf download --local-dir /models/$TARGET_DIR`. The task timeout is 1 hour. A deployment then reads the files at `/models/<TARGET_DIR>`.

## API Gateway and API keys

### How it works

```
client --x-api-key--> API Gateway (*.gateway.dev) --ID token of the gateway SA--> Cloud Run (private)
```

- The Cloud Run service stays private. Only the invokers of the module can call its `run.app` URL.
- The gateway URL is public. The gateway checks the `x-api-key` header before it calls Cloud Run. A request without a valid key gets `401`, and no instance starts.
- The gateway calls Cloud Run as its own service account. That account has `roles/run.invoker` on the service.
- Only the paths in the OpenAPI spec of the deployment go through. All other paths get `404` at the gateway.

The parts are in 2 places:

| Part | Where | Why |
|---|---|---|
| Gateway API and its managed service | `infra/core/gateways.tf` | The key must target the managed service. Its name has a random part, so it must exist in the same root as the key. |
| Shared API key | `infra/core/gateways.tf` | One key for all gateways |
| Gateway service account, `run.invoker`, OpenAPI spec, API config, gateway | `deployments/<name>/gateway.tf` | These belong to one model |
| Streaming | `scripts/gateway-streaming.py` | The provider has no streaming field |

### Get the API key

```sh
cd infra/core
terraform output -raw api_key
```

The key is in the Terraform state. HCP Terraform keeps the state encrypted. The same key works for all gateways in `local.gateway_apis`. The key string stays the same when you add a gateway.

To rotate the key, run the command below. All clients of all gateways must change to the new key at the same time.

WARNING: The old key stops working when the apply is done.

```sh
cd infra/core
terraform apply -replace='google_apikeys_key.gateways[0]'
```

If the key leaks, all gateways are open until you rotate it. Each call with a valid key can start an instance. A budget alert does not stop spend.

### Streaming

API Gateway streaming (chunked responses, SSE) is in Public Preview. You can set it only when you create a gateway, and the Terraform provider cannot set it. So Terraform creates the gateway without streaming. Then `scripts/gateway-streaming.py` makes it again with streaming and the same ID. The script imports the gateway into the state if the state does not have it, and refreshes the state.

WARNING: The gateway URL changes, and the gateway is not available for some minutes.

```sh
./scripts/gateway-streaming.py deployments/<name>   # add --yes to skip the prompt
```

The script loads `.env` itself, so you do not need direnv. It does nothing when the gateway already streams. Run it again after Terraform replaces the gateway.

Streaming limits:

- The `deadline` in the OpenAPI spec is the limit for the whole response, not an idle timeout. When it passes, the gateway stops the stream.
- The `deadline` must not be longer than the Cloud Run request timeout (module `timeout`, default `300s`).
- Streaming gateways have no custom domain and no load balancer during the preview.

### Add a gateway to a new deployment

Example: a new deployment `deployments/stt-a-whisper-cpu`.

1. In `infra/core/gateways.tf`, add the name to `local.gateway_apis`:
   ```hcl
   gateway_apis = [
     "tts-a-kokoro-cpu",
     "stt-a-whisper-cpu",
   ]
   ```
2. Apply `infra/core/`. It creates the API, a placeholder config and the enabled managed service, and adds the service to the key restrictions. The key string does not change.
3. Copy `deployments/tts-a-kokoro-cpu/gateway.tf` to the new deployment. Then change these values:
   - `local.gateway_id`: the same name as in step 1. The name must be 49 characters or less. The gateway service account ID is `<gateway_id>-gw`, so keep the name 27 characters or less.
   - `local.openapi.paths`: only the paths that clients need. Give each operation a unique `operationId`. Do not add `security` to an operation: the global `security` must apply to all paths. The only exception: each path also gets an `options` operation with `security = []`, for the CORS preflight of the test UI (see [Test UI](#test-ui)).
   - `deadline`: not longer than the Cloud Run `timeout` of the module call.
4. In the deployment `main.tf`:
   - Add the `google-beta` provider (in `required_providers` and as a `provider` block).
   - Add the gateway service account to `invokers` and `depends_on` of the module call:
     ```hcl
     invokers   = ["user:${var.invoker_email}", "serviceAccount:${local.gateway_sa}"]
     depends_on = [google_service_account.gateway]
     ```
     Use `local.gateway_sa`, not `google_service_account.gateway.email`. The module uses `invokers` in `for_each`, and the email is not known at plan time.
5. Add `gateway_region` to `variables.tf` and copy the gateway outputs (`gateway_url`, `gateway_id`, `gateway_region`, `api_config`) to `outputs.tf`. The streaming script reads these outputs.
6. Copy `tests/gateway.tftest.hcl` and run `terraform init -backend=false && terraform test`.
7. Apply the deployment. If you need streaming, run `./scripts/gateway-streaming.py deployments/<name>`.
8. Test with `curl` and the key from `terraform -chdir=infra/core output -raw api_key` (see the deployment README).
9. Add the `ui` output and run `./scripts/ui-deploy.py`. Follow the `model-ui` skill (`.claude/skills/model-ui/SKILL.md`).

Vertex AI deployments: step 4 is different. There is no `invokers` list. `gateway.tf` gives the gateway service account `roles/aiplatform.user` on the project, and the backend is the `:rawPredict` URL of the endpoint (`path_translation = "CONSTANT_ADDRESS"`). See `deployments/llm-a-gemma4-12b-vllm-vertex/gateway.tf`. Not verified: Vertex AI may reject the ID token that the gateway sends.

To remove a gateway, destroy the deployment first. Then remove the name from `local.gateway_apis` and apply `infra/core/`.

### Gateway in another GCP project

A key belongs to one GCP project. A gateway accepts the key only if the key project has the managed service of the gateway turned on. Each GCP project has its own `infra/core/` apply, so each GCP project has its own key. To use one key across GCP projects, the key project must turn on the managed service of the other project as a consumer. That needs `roles/servicemanagement.serviceConsumer` on the other project. This repo does not do it.

## Module: model-service

`modules/model-service/` deploys 1 model as 1 private Cloud Run v2 service. The service scales to zero (min 0 instances).

It creates:

- a service account for the service,
- the Cloud Run service (GPU optional),
- `roles/run.invoker` for each member in `invokers`,
- `roles/storage.objectViewer` on `weights_bucket`, if you set one. The bucket is mounted read-only at `/models`.

| Variable | Default | Note |
|---|---|---|
| `project_id`, `region`, `name`, `image` | required | `name`: 6-49 chars, lowercase letters, digits, hyphens. SA ID = `name` if 30 chars or less, else 25 chars + `-` + 4 hash chars. |
| `invokers` | required | IAM members, for example `["user:me@example.com"]`. `allUsers` and `allAuthenticatedUsers` are rejected. |
| `args`, `env` | `[]`, `{}` | Container args and plain env vars. No secrets. |
| `port` | `8080` | Container port. Cloud Run sets `$PORT`. |
| `cpu`, `memory` | `"4"`, `"16Gi"` | Resource limits |
| `gpu_type` | `null` | `"nvidia-l4"` (min 4 CPU, 16Gi) or `"nvidia-rtx-pro-6000"` (min 20 CPU, 80Gi). GCP checks the minimums at apply time. |
| `concurrency` | `4` | Max requests per instance |
| `max_instances` | `1` | Min is always 0 |
| `timeout` | `"300s"` | Request timeout |
| `startup_probe_path` | `null` | HTTP probe path. `null` means a TCP probe. |
| `startup_failure_threshold` | `60` | With a 10 s period: 10 min |
| `weights_bucket` | `null` | Bucket to mount at `/models` |

Billing: a CPU service uses request-based billing (`cpu_idle = true`). A GPU service uses instance-based billing and has zonal redundancy off.

Outputs: `url`, `service_name`, `service_account_email`.

Example:

```hcl
module "service" {
  source = "../../infra/modules/model-service"

  project_id         = var.project_id
  region             = var.region
  name               = "tts-a-kokoro-cpu"
  image              = "europe-west4-docker.pkg.dev/${var.project_id}/ghcr/remsky/kokoro-fastapi-cpu:v0.10.0"
  cpu                = "4"
  memory             = "8Gi"
  startup_probe_path = "/health"
  invokers           = ["user:me@example.com"]
}
```

## Module: vertex-model

Deploys 1 model in a custom container to 1 private, dedicated Vertex AI endpoint. The deployment scales to zero (min 0 replicas, Preview). It is the Vertex AI version of `model-service`. Use 1 call of this module in each `deployments/<name>/` folder. Do not put a list of models in one root.

Terraform creates:

- a service account for the deployed model,
- `roles/storage.objectViewer` on `weights_bucket` for that service account, if you set one,
- a dedicated Vertex AI endpoint (own DNS, no 1.5 MB body limit of the shared endpoint, needed for `:invoke`).

`modules/vertex-model/vertex.sh` does the model upload and the deploy through the Vertex AI REST API (`v1beta1`). Terraform only renders the request bodies (output `vertex`).

### Deploy method: Terraform plus 1 script step

Provider `google ~> 8.10` (checked on 8.10.0) has no resource for a custom-container model upload, and no resource for a deployed model on an existing endpoint.

`google_vertex_ai_endpoint_with_model_garden_deployment` accepts `model_config.container_spec.image_uri`. It does not fit:

- It needs `publisher_model_name` or `hugging_face_model_id`. It deploys a Model Garden or Hugging Face model, not a model from our weights bucket.
- It has no `artifact_uri`, so the container gets no `AIP_STORAGE_URI`.
- It has no `scaleToZeroSpec`, so the idle time stays at the 1 hour default.
- It has no service account and no `invokeRoutePrefix`.

GA `gcloud ai` (SDK 545) has no flags for the idle time, the dedicated endpoint or `invokeRoutePrefix`. So the script calls the REST API with `curl`. HCP Terraform runs have no gcloud login, so the step runs on your machine after `terraform apply`.

### Steps

The deployment root must pass the module output through:

```hcl
output "vertex" {
  value = module.model.vertex
}
```

1. Apply. HCP Terraform creates the endpoint and the service account.
   ```sh
   cd deployments/<name> && terraform apply
   ```
2. Upload and deploy. The script waits for both operations (the deploy can take 30 minutes).
   ```sh
   direnv exec . ../../infra/modules/vertex-model/vertex.sh deploy
   ```
3. Remove. Undeploy first: Vertex AI does not delete an endpoint that has a deployed model. The script also deletes the uploaded model, and a model that a failed deploy left behind.
   ```sh
   direnv exec . ../../infra/modules/vertex-model/vertex.sh undeploy
   terraform destroy
   ```

To change the image, args or machine: run `undeploy`, then `terraform apply`, then `deploy`. `deploy` stops if the endpoint already has a model.

The script needs `terraform`, `gcloud`, `curl` and `jq`.

### Routes

The container must follow the Vertex serving contract:

- It listens on `0.0.0.0:$AIP_HTTP_PORT` (`port`, default 8080).
- `health_route` (default `/health`) returns 200 when the model is ready.
- Set exactly 1 of `predict_route` or `invoke_routes = true`.

Base URL: `DNS=$(terraform output -raw endpoint_dns)`, then `$DNS/v1/projects/<project_id>/locations/<region>/endpoints/<endpoint_id>`. Auth: `-H "Authorization: Bearer $(gcloud auth print-access-token)"`.

| Mode | Call | Goes to |
|---|---|---|
| `predict_route = "/v1/chat/completions"` | `POST <base>:rawPredict` | `predict_route`, body unchanged. Use this for OpenAI JSON. |
| `predict_route = ...` | `POST <base>:predict` with `{"instances": [...]}` | `predict_route`. The response must be `{"predictions": [...]}`. |
| `invoke_routes = true` (Preview) | `POST <base>/invoke/<path>` | `/<path>`, for example `/invoke/v1/chat/completions` to `/v1/chat/completions`. `:predict` and `:rawPredict` are off. HTTP only. |

After you enable a dedicated endpoint, the shared DNS (`<region>-aiplatform.googleapis.com`) does not accept predict calls for it.

### Retry rule for HTTP 429 (scale to zero)

The deployment has `minReplicaCount = 0`, `initialReplicaCount = 1` and `scaleToZeroSpec`. After `idle_scaledown_period` (default 300s, the minimum) without traffic, it scales to 0. `min_scaleup_period` (default 300s) is the time after a scale up before Vertex AI checks for a scale down.

**Rule: when a call returns HTTP 429, the client must wait and send the same request again.**

1. At 0 replicas, the first request starts the scale up. Vertex AI drops that request and returns HTTP 429 ("Model is not yet ready for inference").
2. Retry every 30 s. Use a total limit of 30 minutes. A GPU node start plus the model load takes minutes, not seconds.
3. Retry only on 429. Do not retry other 4xx codes.
4. Treat the first 200 after a 429 as the end of the cold start. Write down the time in the deployment README.

Example:

```sh
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/out.json -w '%{http_code}' -X POST "$URL" \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" -d @body.json)
  [ "$code" != 429 ] && break
  sleep 30
done
echo "$code"; cat /tmp/out.json
```

Other limits of scale to zero (Preview): 1 model per endpoint, no multi-host GPU, quota is reserved for `max_replica_count`, and Vertex AI undeploys a deployment that stays at 0 for more than 30 days. Billing is per node-hour while a replica runs, so each test session bills at least `min_scaleup_period` plus `idle_scaledown_period`.

### Weights flow

Hugging Face → `weights-copy` job → `gs://<project_id>-models/<weights_dir>/` → model `artifactUri` → `$AIP_STORAGE_URI` in the container.

There is no `/models` mount on Vertex AI. The container loads the weights itself from `$AIP_STORAGE_URI`. Vertex AI can point `AIP_STORAGE_URI` to its own copy of `artifactUri`. So always read `$AIP_STORAGE_URI`, not the bucket path. `weights_dir` must match the `TARGET_DIR` of the weights job.

Selected method: **vLLM streams the weights from GCS** with `--load-format runai_streamer`. There is no copy step and no custom image:

```hcl
args = ["--model=$(AIP_STORAGE_URI)", "--load-format=runai_streamer", "--host=0.0.0.0", "--port=8080"]
```

Vertex AI expands `$(VAR)` in `args`. The service account reads the weights bucket (`roles/storage.objectViewer`).

Fallback: if the pinned vLLM cannot read `gs://` with `runai_streamer`, use a custom image with an entrypoint that copies at start (`gcloud storage cp -r "$AIP_STORAGE_URI*" /tmp/model`) and then starts vLLM with `--model=/tmp/model`. The copy adds the full download time to each cold start.

Do not set an `AIP_` variable yourself (validation rejects it).

### Access

The endpoint is private. The module grants no access. A caller needs `aiplatform.endpoints.predict` on the project, for example `roles/aiplatform.user`. Vertex AI has no per-endpoint IAM binding in the provider, and a project-level binding in each deployment root would be removed for all deployments when 1 root is destroyed. Grant the role once, outside the deployments. The project owner already has it. There is no VPC peering and no Private Service Connect; the Vertex AI DNS checks IAM on each call.

### Inputs

| Variable | Default | Note |
|---|---|---|
| `project_id`, `region`, `name`, `image` | required | `name`: 6-49 chars, lowercase letters, digits, hyphens. The endpoint ID is a number derived from `name`. `image` must be in Artifact Registry: use the core `dockerhub_repo` or `ghcr_repo` proxy for stock images. |
| `predict_route` / `invoke_routes` | `null` / `false` | Set exactly 1. |
| `health_route`, `port` | `"/health"`, `8080` | |
| `args`, `env` | `[]`, `{}` | No secrets. No `AIP_` keys. |
| `machine_type`, `accelerator_type`, `accelerator_count` | `"g2-standard-8"`, `"NVIDIA_L4"`, `1` | `accelerator_type = null` for CPU only. |
| `shared_memory_size_mb` | `null` | vLLM: `16384`. |
| `deployment_timeout` | `"1800s"` | Time to start and pass the health check. |
| `max_replica_count` | `1` | Min is always 0. |
| `idle_scaledown_period`, `min_scaleup_period` | `"300s"`, `"300s"` | 300s to 28800s. |
| `weights_bucket`, `weights_dir` | `null` | `weights_dir` needs `weights_bucket`. |

### Outputs

`endpoint_id`, `endpoint_dns`, `service_account_email`, `vertex` (input for `vertex.sh`).

### Example

```hcl
module "model" {
  source = "../../infra/modules/vertex-model"

  project_id            = var.project_id
  region                = var.region
  name                  = "llm-a-gemma4-12b-vllm-vertex"
  image                 = "europe-west4-docker.pkg.dev/${var.project_id}/dockerhub/vllm/vllm-openai:v0.33.0"
  args                  = ["--model=$(AIP_STORAGE_URI)", "--load-format=runai_streamer", "--host=0.0.0.0", "--port=8080"]
  predict_route         = "/v1/chat/completions"
  shared_memory_size_mb = 16384
  weights_bucket        = "${var.project_id}-models"
  weights_dir           = "gemma-4-12b-it-qat-w4a16"
}

output "vertex" {
  value = module.model.vertex
}
```

### Not verified against real GCP

The first deployment card (LLM-A on Vertex AI) checks these:

1. vLLM `runai_streamer` reads `gs://` in the pinned image (research open question 5).
2. Vertex AI expands `$(AIP_STORAGE_URI)` in `args`, and the service account can read the URI that Vertex AI sets.
3. `invokeRoutePrefix` sits in `containerSpec` in `v1beta1`, and the `<base>/invoke/<path>` URL form.
4. The L4 quota for Vertex AI prediction in `europe-west4` (see [Vertex AI GPU quota](#vertex-ai-gpu-quota-check-before-the-first-vertex-ai-deployment)).

## Test UI

A static React app (`ui/`) to test the models in a browser, also on a phone. It has 1 tab for each model. There is no backend: the browser calls the API Gateways with the shared API key. The key stays in the `localStorage` of the browser.

- URL: `terraform -chdir=infra/core output -raw ui_url` (`https://storage.googleapis.com/<project_id>-ui/index.html`).
- Tabs come from `models.json`. `scripts/ui-deploy.py` writes it from the `ui` output of each deployment. A deployment shows in the UI only after it is applied with a `ui` output.
- The gateway URL changes when Terraform or `scripts/gateway-streaming.py` replaces the gateway. Then run `./scripts/ui-deploy.py --config-only`.
- To add a model, a feature or a new model type, use the `model-ui` skill (`.claude/skills/model-ui/SKILL.md`).

```sh
./scripts/ui-deploy.py                # models.json + build + upload all
./scripts/ui-deploy.py --config-only  # only models.json (after a gateway URL change)
./scripts/ui-deploy.py --local        # models.json in ui/public, for npm run dev
```

CORS: the browser sends a preflight `OPTIONS` request before each call, because of the `x-api-key` header. The preflight has no key. So each gateway path has an `options` operation with `security = []`. The gateway sends it to the backend, and the backend answers it:

| Backend | CORS | Status |
|---|---|---|
| Kokoro (Cloud Run) | On by default (`cors_origins = ["*"]` in Kokoro-FastAPI) | Not checked through the gateway |
| vLLM on Vertex AI (`:rawPredict`) | vLLM sends `Access-Control-Allow-Origin: *` by default | Not verified: Vertex AI may reject `OPTIONS` on `:rawPredict` or drop the headers |

If the browser shows "Network or CORS error" for the LLM tab, put a small proxy on Cloud Run between the gateway and the endpoint. It answers `OPTIONS`, adds the CORS headers and calls Vertex AI with an access token. It also fixes the ID-token problem in the Vertex AI gateway section above.

Local work: `cd ui && npm install && npm run mock` (fake TTS and LLM on port 5181, key `test`), then in a second terminal `cp public/models.mock.json public/models.json && npm run dev`.

## Tests

The tests use mock providers. They need no GCP credentials.

```sh
cd infra/core && terraform init -backend=false && terraform test                             # core
cd infra/modules/model-service && terraform init -backend=false && terraform test            # module
cd infra/modules/vertex-model && terraform init -backend=false && terraform test             # Vertex AI module
cd deployments/tts-a-kokoro-cpu && terraform init -backend=false && terraform test           # gateway spec
cd deployments/llm-a-gemma4-12b-vllm-vertex && terraform init -backend=false && terraform test   # Vertex gateway spec
```

The test UI has its own unit tests: `cd ui && npm install && npm test`.
