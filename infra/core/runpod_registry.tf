# Runpod pulls own images (STT-A speech_engine) from the private Artifact Registry repo models with this credential.
# A service account that may only read the repo models, and its JSON key as the registry password
# (username "_json_key"). The platform-runpod adapter finds the credential by its name "gcp-models".
# The key is in the state of this root (sensitive). Accepted in docs/specs/2026-11-22-multi-platform-design.md
# ("Secrets and keys"): it is a read-only pull key. Rotate: taint google_service_account_key.runpod_pull and apply.
resource "google_service_account" "runpod_pull" {
  project      = var.project_id
  account_id   = "runpod-pull"
  display_name = "Runpod image pull (read-only, repo models)"
}

resource "google_artifact_registry_repository_iam_member" "runpod_pull" {
  project    = var.project_id
  location   = google_artifact_registry_repository.models.location
  repository = google_artifact_registry_repository.models.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.runpod_pull.email}"
}

resource "google_service_account_key" "runpod_pull" {
  service_account_id = google_service_account.runpod_pull.name
}

resource "runpod_registry" "gcp_models" {
  name     = "gcp-models"
  username = "_json_key"
  password = base64decode(google_service_account_key.runpod_pull.private_key)
}

# The same read-only key for Modal: scripts/platforms/modal.py reads it at deploy time and gives it to Modal as the
# registry secret (SERVICE_ACCOUNT_JSON). Sensitive: `terraform output -raw registry_pull_key` prints it.
output "registry_pull_key" {
  description = "JSON key of the read-only pull service account (repo models). For the Modal image pull."
  value       = base64decode(google_service_account_key.runpod_pull.private_key)
  sensitive   = true
}
