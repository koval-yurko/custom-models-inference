locals {
  base = "https://${local.endpoint_dns}/v1/projects/${var.project_id}/locations/${var.region}/endpoints/${google_vertex_ai_endpoint.this.name}"
}

output "target" {
  description = "The common adapter output. The model facade merges it into targets."
  value = {
    id    = "vertex"
    label = "Vertex AI"
    # predict_route: one fixed :rawPredict URL. Else the :invoke base; the proxy appends the route.
    url         = local.predict_route != null ? "${local.base}:rawPredict" : "${local.base}/invoke"
    append_path = local.predict_route == null
    auth        = "google"
    cold_start  = "retry-429" # at 0 replicas Vertex AI returns 429 at once
    deadline    = 300
    post_apply  = "vertex" # scripts/platforms/vertex.py uploads and deploys the model
  }

  precondition {
    condition     = local.gpu == null || contains(keys(local.accelerators), coalesce(local.gpu, "-"))
    error_message = "spec.gpu must be \"L4\" or null on Vertex AI."
  }
}

output "vertex" {
  description = "Input for scripts/platforms/vertex.py."
  value = {
    project        = var.project_id
    region         = var.region
    endpoint       = google_vertex_ai_endpoint.this.id
    endpoint_dns   = local.endpoint_dns
    name           = local.name
    invoke_routes  = local.invoke_routes
    predict_route  = local.predict_route
    model_upload   = local.model_upload
    deployed_model = local.deployed_model
  }
}

output "endpoint_id" {
  description = "Numeric endpoint ID."
  value       = google_vertex_ai_endpoint.this.name
}

output "endpoint_dns" {
  description = "Dedicated endpoint DNS."
  value       = local.endpoint_dns
}

output "service_account_email" {
  description = "Service account the deployed model runs as."
  value       = google_service_account.this.email
}
