# API key of the GPU platform Runpod. The CORS proxy of each model reads them as
# secret env vars (infra/modules/model sets secret_env). The browser never sees them.
resource "google_secret_manager_secret" "runpod_api_key" {
  project   = var.project_id
  secret_id = "runpod-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# Write-only: the key is not in Terraform state. To rotate it, change RUNPOD_API_KEY in .env, run
# scripts/hcp-sync.py and raise secret_data_wo_version.
resource "google_secret_manager_secret_version" "runpod_api_key" {
  secret                 = google_secret_manager_secret.runpod_api_key.id
  secret_data_wo         = var.runpod_api_key
  secret_data_wo_version = 1
}
