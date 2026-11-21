# Files service (upload/upload.py): upload URLs, the file list, transcript history and "transcribe again".
# CPU only, so a client gets a URL or the history without a GPU cold start. It runs in the stock Python image, as the
# CORS proxy. "transcribe again" calls the GPU service (:rawPredict) and saves the answer as a new version.
locals {
  upload_env = {
    AUDIO_BUCKET = local.audio_bucket
    SA_EMAIL     = module.upload.service_account_email # it signs the URL as itself (signBlob)
    IMAGE_TAG    = var.image_tag                       # stored in each version: which GPU image made it
    TARGET       = local.raw_predict_url
  }
}

module "upload" {
  source = "../../infra/modules/model-service"

  project_id = var.project_id
  region     = var.region
  name       = "${local.gateway_id}-files"
  image      = "${var.region}-docker.pkg.dev/${var.project_id}/dockerhub/library/python:3.13.9-slim"
  command    = ["python3"]
  args       = ["-u", "-c", file("${path.module}/upload/upload.py")]
  env        = local.upload_env

  cpu           = "1"
  memory        = "256Mi"
  concurrency   = 80
  max_instances = 2
  timeout       = "900s" # transcribe waits for the GPU; Vertex AI stops a request at 600 s
  invokers      = []     # the gateway SA is unknown at plan time on a first apply, so no for_each
}

resource "google_cloud_run_v2_service_iam_member" "upload_gateway" {
  project  = var.project_id
  location = var.region
  name     = module.upload.service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.gateway.email}"
}

# Create and read only: the SA cannot replace or delete audio or versions.
resource "google_storage_bucket_iam_member" "upload_create" {
  bucket = local.audio_bucket
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${module.upload.service_account_email}"
}

resource "google_storage_bucket_iam_member" "upload_read" {
  bucket = local.audio_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${module.upload.service_account_email}"
}

# The provider has no IAM resource for 1 Vertex AI endpoint, so the role is on the project (as the CORS proxy).
resource "google_project_iam_member" "upload_predict" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${module.upload.service_account_email}"
}

# signBlob as itself, for the V4 signature. No key file.
resource "google_service_account_iam_member" "upload_sign" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${module.upload.service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${module.upload.service_account_email}"
}
