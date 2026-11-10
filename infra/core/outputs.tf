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

output "dockerhub_repo" {
  description = "Image URL prefix that proxies Docker Hub, for example <dockerhub_repo>/vllm/vllm-openai:v0.33.0. Vertex AI needs it."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.dockerhub.repository_id}"
}

output "region" {
  value = var.region
}

output "weights_copy_job" {
  description = "Cloud Run job that copies a Hugging Face repo into weights_bucket."
  value       = google_cloud_run_v2_job.weights_copy.name
}

output "gateway_apis" {
  description = "Gateway API ID -> managed service. A deployment with the same API ID adds its gateway to it."
  value       = { for k, v in google_api_gateway_api.this : k => v.managed_service }
}

output "api_key" {
  description = "Shared API key for the x-api-key header of all model gateways. It is in the state."
  value       = one(google_apikeys_key.gateways[*].key_string)
  sensitive   = true
}
