# Private Cloud Run proxy that adds CORS headers to every answer of Vertex AI (see infra/modules/cors-proxy).
# The target is :rawPredict: 1 fixed URL, the predict_route of main.tf (/v1beta/interactions).
locals {
  # The 1 route of the GPU service. The CORS proxy and the STT API service (stt_api.tf) both call it.
  raw_predict_url = "https://${module.model.endpoint_dns}/v1/projects/${var.project_id}/locations/${var.region}/endpoints/${module.model.endpoint_id}:rawPredict"
}

module "cors_proxy" {
  source = "../../infra/modules/cors-proxy"

  project_id                    = var.project_id
  region                        = var.region
  name                          = "${local.gateway_id}-proxy"
  image                         = "${var.region}-docker.pkg.dev/${var.project_id}/dockerhub/library/python:3.13.9-slim"
  target                        = local.raw_predict_url
  gateway_service_account_email = google_service_account.gateway.email
}
