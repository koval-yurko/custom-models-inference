# Design: GCP bootstrap, model-service module, TTS-A Kokoro (CPU)

> Update: Terraform state now lives in HCP Terraform workspaces, not GCS. The `<project_id>-tfstate` bucket and `backend "gcs"` blocks below are replaced by `cloud {}` blocks. See `infra/bootstrap/README.md`.
> Update: variable values now come from `.env` as `TF_VAR_*` (see `.envrc`). The `terraform.tfvars` files described below do not exist.

Date: 2026-11-09. Card: "1. Bootstrap GCP + model-service module + TTS-A Kokoro (CPU)".
Inputs: `docs/research/01-serverless-inference-on-gcp.md`, `docs/research/03-speech-models.md`.

## Intent

Build the shared base for all model deployments, and deploy the cheapest model first.
TTS-A needs no GPU quota. It tests Terraform, the shared module and Cloud Run at the lowest cost.
All later cards (LLM, STT, TTS-B) reuse the bootstrap and the module.

## Goals

1. `infra/bootstrap/` prepares one GCP project for all deployments.
2. `infra/modules/model-service/` deploys one model as one private Cloud Run v2 service.
3. `deployments/tts-a-kokoro-cpu/` deploys Kokoro-82M with the stock CPU image.
4. The README files give the exact commands to apply, test, check scale to zero and destroy.

Done when (from the card): terraform apply works for bootstrap and tts-a, a POST to `/v1/audio/speech` returns audio, the service scales to zero, and terraform destroy removes tts-a.

## Non-goals

- The Hugging Face token secret and the weights copy job. They come with the weights card.
- Custom images, Cloud Build pipelines, GPU deployments.
- CI, public access, custom domains, VPC.

## Anti-goals

- No public service. Never grant `roles/run.invoker` to `allUsers` or `allAuthenticatedUsers`.
- No minimum instances above 0. An idle service must cost nothing.
- No list of models in one Terraform root. One folder and one state per deployment (project convention).

## Decisions by the user (2026-11-09)

| Topic | Decision |
|---|---|
| Region | `europe-west4` for all buckets, repos and services. It has L4 and RTX PRO 6000 on Cloud Run for later cards. |
| Budget | $20 per month. Email alerts only; a budget does not stop spend. |
| Project | A new dedicated project. The user creates it and links billing. Terraform does not create the project. |
| Verification | Code only in this card. The agent runs `terraform fmt` and `terraform validate`. The user runs apply, the test call and destroy. |

## Constraints and facts checked

1. Cloud Run cannot pull images from `ghcr.io` directly. Use an Artifact Registry remote repository with GitHub Container Registry as the upstream ([Cloud Run deploy docs](https://docs.cloud.google.com/run/docs/deploying)).
2. The image `ghcr.io/remsky/kokoro-fastapi-cpu` (latest release `v0.10.0`, 2026-11-08) starts uvicorn on `${PORT:-8880}`. Cloud Run sets `PORT=8080`, so no port setting is necessary.
3. The model weights are inside the image. The image has `GET /health`.
4. The `google_billing_budget` resource uses the Billing Budget API. With user credentials (ADC), the provider needs a quota project: `user_project_override = true` and `billing_project = var.project_id`.
5. The google provider (v6 and later) sets `deletion_protection = true` on `google_cloud_run_v2_service` by default. The module sets it to `false`, so `terraform destroy` works.
6. Terraform 1.14 and gcloud are installed on the user's machine.

## Design

### infra/bootstrap/

A Terraform root that the user applies one time per project.

Inputs (`terraform.tfvars`, tracked in git, no secrets):

- `project_id` (string)
- `billing_account` (string, for example `0X0X0X-0X0X0X-0X0X0X`)
- `region` (default `europe-west4`)
- `budget_amount` (default `20`, a whole number in the billing account currency)

Resources:

1. `google_project_service` for `run`, `artifactregistry`, `cloudbuild`, `secretmanager`, `storage`, `compute`, `billingbudgets`, `iam`, `cloudresourcemanager`, `serviceusage`. Set `disable_on_destroy = false`. The `google_project` data source has `depends_on` on the APIs, and the README tells the user to enable `serviceusage` and `cloudresourcemanager` with gcloud first.
2. State bucket `<project_id>-tfstate`: uniform bucket-level access, versioning on, public access prevention enforced.
3. Weights bucket `<project_id>-models`: same settings, no versioning. No deployment uses it in this card.
4. Artifact Registry Docker repo `models` (standard) for custom images in later cards.
5. Artifact Registry Docker repo `ghcr` (remote), upstream `https://ghcr.io`. Images resolve as `<region>-docker.pkg.dev/<project_id>/ghcr/<owner>/<image>:<tag>`.
6. `google_billing_budget` on the billing account, filtered to this project, amount `budget_amount`, thresholds 0.5, 0.9 and 1.0. Default recipients (billing account admins and users).

Outputs: `state_bucket`, `weights_bucket`, `models_repo`, `ghcr_repo` (the image URL prefix), `region`.

State: bootstrap starts with local state, because its bucket does not exist yet. After the first apply, the user adds a `backend.tf` with `bucket = "<project_id>-tfstate"` and `prefix = "infra/bootstrap"`, then runs `terraform init -migrate-state`. The README gives these steps. The repo ships `backend.tf.example`, so the first `init` stays local.

### infra/modules/model-service/

A module that deploys one model. It has no provider or backend block.

Inputs:

| Variable | Default | Note |
|---|---|---|
| `project_id`, `region`, `name` | required | `name` is the Cloud Run service name and the base of the SA name |
| `image` | required | full image URL |
| `args`, `env` | `[]`, `{}` | container args, plain env vars |
| `port` | `8080` | container port |
| `cpu`, `memory` | `"4"`, `"16Gi"` | resource limits |
| `gpu_type` | `null` | `"nvidia-l4"` or `"nvidia-rtx-pro-6000"`; `null` means CPU only |
| `concurrency` | `4` | max requests per instance |
| `max_instances` | `1` | min is always 0 |
| `timeout` | `"300s"` | request timeout |
| `startup_probe_path` | `null` | HTTP probe path; `null` means a TCP probe |
| `startup_failure_threshold` | `60` | with a 10 s period: 10 min |
| `weights_bucket` | `null` | when set, mount it read-only at `/models` and grant the SA `roles/storage.objectViewer` on it |
| `invokers` | required | list of IAM members, for example `["user:me@example.com"]` |

Resources:

1. `google_service_account` for the service. Its account ID is `name` when it is 30 characters or less, else the first 25 characters, a hyphen and 4 hex characters of the sha256 of `name`. `name` must be 6-49 characters of lowercase letters, digits and hyphens.
2. `google_cloud_run_v2_service`:
   - `ingress = "INGRESS_TRAFFIC_ALL"`, `deletion_protection = false`.
   - `scaling`: min 0, max `max_instances`.
   - With a GPU: `node_selector.accelerator = gpu_type`, limit `nvidia.com/gpu = 1`, `gpu_zonal_redundancy_disabled = true`, `cpu_idle = false`.
   - Without a GPU: `cpu_idle = true` (request-based billing, so an idle instance costs nothing).
   - `startup_cpu_boost = true`.
   - Startup probe: HTTP or TCP on `port`.
   - The volume and mount only when `weights_bucket` is set.
3. `google_cloud_run_v2_service_iam_member` with `roles/run.invoker` for each item of `invokers`.
4. `google_storage_bucket_iam_member` with `roles/storage.objectViewer` when `weights_bucket` is set.

Outputs: `url`, `service_name`, `service_account_email`.

### deployments/tts-a-kokoro-cpu/

The files follow the project convention: `main.tf`, `backend.tf`, `terraform.tfvars`, `README.md`. There is no `image/` folder, because the image is public.

- `backend.tf`: GCS backend, `prefix = "deployments/tts-a-kokoro-cpu"`. The bucket name comes from `terraform init -backend-config="bucket=<project_id>-tfstate"`, so the file has no project ID in it.
- `main.tf`: the provider, plus one call to the module:
  - `image = "${region}-docker.pkg.dev/${project_id}/ghcr/remsky/kokoro-fastapi-cpu:v0.10.0"`
  - `cpu = "4"`, `memory = "8Gi"`, no GPU, no weights bucket
  - `startup_probe_path = "/health"`
  - `invokers = ["user:${var.invoker_email}"]`
- `terraform.tfvars`: `project_id`, `region`, `invoker_email`.
- Output: `url`.

README steps (the user runs them):

1. `terraform init -backend-config="bucket=<project_id>-tfstate"` and `terraform apply`.
2. Test call:
   ```sh
   URL=$(terraform output -raw url)
   curl -sS -X POST "$URL/v1/audio/speech" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"model":"kokoro","input":"Hello from Cloud Run.","voice":"af_heart","response_format":"mp3"}' \
     -o out.mp3 && file out.mp3
   ```
   The expected result is an MPEG audio file.
3. Scale to zero: wait about 15 minutes with no requests. Then check the instance count metric `run.googleapis.com/container/instance_count` in Cloud Monitoring for the service (it must be 0), or open the service Metrics tab in the console.
4. `terraform destroy`, then `gcloud run services list --region europe-west4` must not show `tts-a-kokoro-cpu`.

## Prerequisites for the user

1. Create the project and link billing.
2. `gcloud auth login` and `gcloud auth application-default login`. The current gcloud token is expired.
3. `gcloud auth application-default set-quota-project <project_id>`.
4. The user's account needs the Owner role on the project and Billing Account Costs Manager (or Administrator) on the billing account, for the budget.

## Calls made by the agent

- An Artifact Registry remote repo named `ghcr`, not a manual image copy.
- Bootstrap uses local state first, then moves it into the bucket.
- The image tag is pinned to `v0.10.0`, not `latest`.
- The CPU service uses `cpu_idle = true`.
- Concurrency 4, max instances 1, request timeout 300 s.
- The budget alerts go to the default billing recipients. There is no extra email channel.
- The `billingbudgets` and `iam` APIs are added to the card's API list.
- The `invokers` list holds only the user's account.
- The budget filter uses the project number from a `google_project` data source (the API needs `projects/<number>`).
- The buckets, repos and budget use `depends_on` on the API resources, so the first apply works in one pass.
- The startup probe period is 10 s with 60 failures (10 min). Check this against the Cloud Run probe limits during the build.

## Left to the builder

- Exact provider version constraint (google `~> 7.0` or the current major), after a check of the provider docs.
- Exact argument names. Check each one against the current `hashicorp/google` docs.
- Default Kokoro voice name, if `af_heart` is not in `v0.10.0`.
