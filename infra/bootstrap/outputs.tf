output "state_bucket" {
  value = google_storage_bucket.tfstate.name
}

output "weights_bucket" {
  value = google_storage_bucket.models.name
}

output "models_repo" {
  description = "Image URL prefix for custom images."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.models.repository_id}"
}

output "ghcr_repo" {
  description = "Image URL prefix that proxies ghcr.io, for example <ghcr_repo>/remsky/kokoro-fastapi-cpu:v0.10.0."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ghcr.repository_id}"
}

output "region" {
  value = var.region
}
