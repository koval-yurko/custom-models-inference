# Runpod S3 API key (not the Runpod API key). scripts/runpod-weights.py --cloud copies weights to a Runpod network
# volume from a Cloud Build job, so the copy does not depend on the upload speed of a laptop. The job reads these
# 2 secrets. Write-only: the values are not in Terraform state. To rotate: change RUNPOD_S3_* in .env, run
# scripts/hcp-sync.py and raise secret_data_wo_version.
locals {
  runpod_s3_secrets = ["runpod-s3-access-key", "runpod-s3-secret-key"]
  # Cloud Build runs as the default compute service account in this project.
  cloud_build_sa = "serviceAccount:${data.google_project.this.number}-compute@developer.gserviceaccount.com"
}

resource "google_secret_manager_secret" "runpod_s3" {
  for_each = toset(local.runpod_s3_secrets)

  project   = var.project_id
  secret_id = each.key

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "runpod_s3_access_key" {
  secret                 = google_secret_manager_secret.runpod_s3["runpod-s3-access-key"].id
  secret_data_wo         = var.runpod_s3_access_key
  secret_data_wo_version = 1
}

resource "google_secret_manager_secret_version" "runpod_s3_secret_key" {
  secret                 = google_secret_manager_secret.runpod_s3["runpod-s3-secret-key"].id
  secret_data_wo         = var.runpod_s3_secret_key
  secret_data_wo_version = 1
}

resource "google_secret_manager_secret_iam_member" "runpod_s3_cloud_build" {
  for_each = google_secret_manager_secret.runpod_s3

  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.cloud_build_sa
}
