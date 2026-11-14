# Private Cloud Run proxy that adds CORS headers to every answer of Vertex AI (see infra/modules/cors-proxy).
module "cors_proxy" {
  source = "../../infra/modules/cors-proxy"

  project_id                    = var.project_id
  region                        = var.region
  name                          = "${local.gateway_id}-proxy"
  image                         = "${var.region}-docker.pkg.dev/${var.project_id}/dockerhub/library/python:3.13.9-slim"
  target                        = "https://${module.model.endpoint_dns}/v1/projects/${var.project_id}/locations/${var.region}/endpoints/${module.model.endpoint_id}:rawPredict"
  gateway_service_account_email = google_service_account.gateway.email
}
