output "url" {
  description = "Service URL."
  value       = google_cloud_run_v2_service.this.uri
}

output "service_name" {
  description = "Cloud Run service name."
  value       = google_cloud_run_v2_service.this.name
}

output "service_account_email" {
  description = "Service account the service runs as."
  value       = google_service_account.this.email
}
