# Bootstrap

Run this one time per GCP project. It prepares the project for all deployments under `deployments/`.

It creates:

- the APIs: run, artifactregistry, cloudbuild, secretmanager, storage, compute, billingbudgets, iam, cloudresourcemanager, serviceusage,
- the bucket `<project_id>-tfstate` for Terraform state (versioned),
- the bucket `<project_id>-models` for model weights,
- the Artifact Registry Docker repo `models` for custom images,
- the Artifact Registry remote repo `ghcr`, a proxy for `ghcr.io` (Cloud Run cannot pull from `ghcr.io` directly),
- a monthly billing budget with email alerts at 50%, 90% and 100%. A budget does not stop spend,
- the Secret Manager secret `hf-token` (no value; add it with `printf '%s' "$HF_TOKEN" | gcloud secrets versions add hf-token --data-file=-`),
- the Cloud Run job `weights-copy` and its service account. The job copies 1 Hugging Face repo into `<project_id>-models/<TARGET_DIR>/`. It has write access to the weights bucket and read access to `hf-token` only.

All resources go in `europe-west4` by default.

## Prerequisites

1. Create the project and link it to a billing account.
2. Log in:
   ```sh
   gcloud auth login
   gcloud auth application-default login
   gcloud auth application-default set-quota-project <project_id>
   ```
3. Turn on the 2 APIs that Terraform needs before it can turn on the others:
   ```sh
   gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com --project <project_id>
   ```
4. Your account needs the Owner role on the project, and Billing Account Costs Manager (or Billing Account Administrator) on the billing account.
5. Put `project_id` and `billing_account` in `terraform.tfvars`. Find the billing account ID with `gcloud billing accounts list`.

## First apply (local state)

The state bucket does not exist yet, so the first apply uses local state.

```sh
cd infra/bootstrap
terraform init
terraform apply
```

## Move the state into the bucket

```sh
cp backend.tf.example backend.tf
# Edit backend.tf: set bucket = "<project_id>-tfstate"
terraform init -migrate-state
```

Answer `yes`. Then delete the local `terraform.tfstate` and `terraform.tfstate.backup` files. Commit `backend.tf`.

## Outputs

`state_bucket`, `weights_bucket`, `models_repo`, `ghcr_repo`, `region`, `weights_copy_job`. The deployments use `state_bucket` and `ghcr_repo`.

## Copy model weights

Run the job 1 time per model. Set the repo and the target folder for each execution:

```sh
gcloud run jobs execute weights-copy --region europe-west4 --wait \
  --update-env-vars HF_REPO=google/gemma-4-12B-it-qat-w4a16-ct,TARGET_DIR=gemma-4-12b-it-qat-w4a16
```

The job mounts the bucket with GCS FUSE at `/models` and runs `hf download --local-dir /models/$TARGET_DIR`. The task timeout is 1 hour. A deployment then reads the files at `/models/<TARGET_DIR>`.
