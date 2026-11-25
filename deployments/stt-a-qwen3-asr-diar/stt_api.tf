# STT API service (services/stt_api/, package stt_api): upload URLs, the file list, transcript history,
# "transcribe again" and the evaluation scores. CPU only, so a client gets a URL or the history without a GPU cold
# start. Own image (services/stt_api/cloudbuild.yaml), standard library only. "transcribe again" calls the GPU service
# through the CORS proxy of the model (<proxy>/<platform>/v1beta/interactions, with a Google ID token), so the
# provider keys stay in the proxy. It sends a signed audio URL: the GPU service needs no GCP credentials.
locals {
  stt_api_image = "${var.region}-docker.pkg.dev/${var.project_id}/models/stt-a-qwen3-asr-diar-api:${var.stt_api_image_tag}"
  stt_api_env = {
    AUDIO_BUCKET = local.audio_bucket
    SA_EMAIL     = module.stt_api.service_account_email # it signs the URL as itself (signBlob)
    IMAGE_TAG    = var.image_tag                        # stored in each version: which GPU image made it
    TARGET       = module.model.proxy_url
    PLATFORMS    = join(",", local.platforms) # a path prefix picks one; no prefix: the first
  }
}

module "stt_api" {
  source = "../../infra/modules/model-service"

  project_id = var.project_id
  region     = var.region
  name       = "${local.gateway_id}-api"
  image      = local.stt_api_image
  env        = local.stt_api_env

  cpu           = "1"
  memory        = "256Mi"
  concurrency   = 80
  max_instances = 2
  timeout       = "900s" # transcribe waits for the GPU; Vertex AI stops a request at 600 s
  invokers      = []     # the gateway SA is unknown at plan time on a first apply, so no for_each
}

resource "google_cloud_run_v2_service_iam_member" "stt_api_gateway" {
  project  = var.project_id
  location = var.region
  name     = module.stt_api.service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${module.model.gateway_service_account_email}"
}

# Create and read. Replace and delete: see stt_api_names.
resource "google_storage_bucket_iam_member" "stt_api_create" {
  bucket = local.audio_bucket
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${module.stt_api.service_account_email}"
}

resource "google_storage_bucket_iam_member" "stt_api_read" {
  bucket = local.audio_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${module.stt_api.service_account_email}"
}

# Speaker names and the reference change, and the UI deletes files, versions and references, so the SA may replace
# and delete objects under files/. The code replaces only *.names.json and reference.json (stt_api/gcp.py write).
# The condition needs uniform bucket-level access (infra/core main.tf sets it).
resource "google_storage_bucket_iam_member" "stt_api_names" {
  bucket = local.audio_bucket
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${module.stt_api.service_account_email}"
  condition {
    title       = "files-only"
    description = "Replace and delete only the objects under files/"
    expression  = "resource.name.startsWith(\"projects/_/buckets/${local.audio_bucket}/objects/files/\")"
  }
}

# signBlob as itself, for the V4 signature. No key file.
resource "google_service_account_iam_member" "stt_api_sign" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${module.stt_api.service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${module.stt_api.service_account_email}"
}
