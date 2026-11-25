# API keys of the GPU platforms Runpod and Modal. The CORS proxy of each model reads them as
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

# Modal proxy token (the part after "Bearer ": wk-<id>.ws-<secret>) for the Modal web endpoints of own images.
# Make it with `uvx modal workspace proxy-tokens create`. Write-only, as the Runpod key.
resource "google_secret_manager_secret" "modal_api_key" {
  project   = var.project_id
  secret_id = "modal-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "modal_api_key" {
  secret                 = google_secret_manager_secret.modal_api_key.id
  secret_data_wo         = var.modal_api_key
  secret_data_wo_version = 1
}
