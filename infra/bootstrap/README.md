# Bootstrap

Run this one time per GCP project. It prepares the project for all deployments under `deployments/`.

It creates:

- the APIs: run, artifactregistry, cloudbuild, secretmanager, storage, compute, billingbudgets, iam, cloudresourcemanager, serviceusage,
- the bucket `<project_id>-models` for model weights,
- the Artifact Registry Docker repo `models` for custom images,
- the Artifact Registry remote repo `ghcr`, a proxy for `ghcr.io` (Cloud Run cannot pull from `ghcr.io` directly),
- a monthly billing budget with email alerts at 50%, 90% and 100%. A budget does not stop spend,
- the Secret Manager secret `hf-token` and its value, taken from `HF_TOKEN` in `.env` (write-only: the value is not in the Terraform state). To rotate it, change `HF_TOKEN` and raise `secret_data_wo_version` in `weights_copy.tf`,
- the Cloud Run job `weights-copy` and its service account. The job copies 1 Hugging Face repo into `<project_id>-models/<TARGET_DIR>/`. It has write access to the weights bucket and read access to `hf-token` only.

All resources go in `europe-west4` by default. Set `GCP_REGION` in `.env` to change it.

## Prerequisites

1. Create the project and link it to a billing account.
2. Create a service account key (see `.env.example`) and put its path in `GOOGLE_APPLICATION_CREDENTIALS` in `.env`. Terraform and gcloud both use this key. `.envrc` sets `CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE` to the same file and `CLOUDSDK_CONFIG` to the local `.gcloud/` folder. So gcloud never uses your global login or config. Do not run `gcloud auth login` for this project. Check: `gcloud auth print-access-token >/dev/null && echo ok`.
3. Turn on the 2 APIs that Terraform needs before it can turn on the others:
   ```sh
   gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com 
   ```
4. The service account needs the Owner role on the project, and Billing Account Costs Manager (or Billing Account Administrator) on the billing account.
5. Put `GCP_PROJECT_ID` and `BILLING_ACCOUNT` in `.env` (see `.env.example`). `.envrc` maps them to `TF_VAR_project_id` and `TF_VAR_billing_account`. Find the billing account ID with `gcloud billing accounts list`. There is no `terraform.tfvars` file.

## State (HCP Terraform)

State lives in HCP Terraform, not in the project. Do this once, before the first apply:

1. Create an HCP Terraform organization and a project (for example `custom-models-inference`).
2. Copy `.env.example` to `.env` in the repo root and fill it in. Run `direnv allow` once in the repo root. direnv then loads `.env` whenever you enter the folder. The commands in all READMEs assume `.env` is loaded. Check it with `echo $TF_CLOUD_ORGANIZATION`. (Without direnv: `set -a; source .env; set +a` in each shell.)
   `TF_TOKEN_app_terraform_io` replaces `terraform login`.
3. Run `terraform init` in each root. It creates the workspace in the project from `TF_CLOUD_PROJECT` if it does not exist.
4. In each workspace, set Settings > General > Execution Mode to **Local**. A new workspace starts with the organization default, so you can set that default to Local once (Organization settings > Defaults). Terraform then runs on your machine with your GCP credentials, and HCP only stores the state.

The workspace name is in `backend.tf` in each root.

## Apply

```sh
cd infra/bootstrap
terraform init
terraform apply
```

## Outputs

`weights_bucket`, `models_repo`, `ghcr_repo`, `region`, `weights_copy_job`. The deployments use `ghcr_repo`.

## Copy model weights

Run the job 1 time per model. Set the repo and the target folder for each execution:

```sh
gcloud run jobs execute weights-copy --wait \
  --update-env-vars HF_REPO=google/gemma-4-12B-it-qat-w4a16-ct,TARGET_DIR=gemma-4-12b-it-qat-w4a16
```

The job mounts the bucket with GCS FUSE at `/models` and runs `hf download --local-dir /models/$TARGET_DIR`. The task timeout is 1 hour. A deployment then reads the files at `/models/<TARGET_DIR>`.
