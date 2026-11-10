output "endpoint_id" {
  description = "Numeric endpoint ID."
  value       = google_vertex_ai_endpoint.this.name
}

output "endpoint_dns" {
  description = "Dedicated endpoint DNS: https://<endpoint_id>.<region>-<project_number>.prediction.vertexai.goog."
  value       = google_vertex_ai_endpoint.this.dedicated_endpoint_dns
}

output "service_account_email" {
  description = "Service account the deployed model runs as."
  value       = google_service_account.this.email
}

output "vertex" {
  description = "Input for vertex.sh. Pass it through as an output named vertex in the deployment root."
  value = {
    project        = var.project_id
    region         = var.region
    endpoint       = google_vertex_ai_endpoint.this.id
    endpoint_dns   = google_vertex_ai_endpoint.this.dedicated_endpoint_dns
    name           = var.name
    invoke_routes  = var.invoke_routes
    predict_route  = var.predict_route
    model_upload   = local.model_upload
    deployed_model = local.deployed_model
  }
}
