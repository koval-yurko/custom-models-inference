# CORS preflight answer for the API Gateways of the test UI (see infra/README.md, "CORS preflight service").
# Vertex AI does not answer OPTIONS on :rawPredict. A gateway sends the OPTIONS operation of its paths here instead.
# The service is private. Each deployment gives run.invoker to its own gateway service account (deployments/*/gateway.tf).
# Its URL is https://cors-preflight-<project number>.<region>.run.app, so a deployment builds it without core state.

module "cors_preflight" {
  source = "../modules/model-service"

  project_id = var.project_id
  region     = var.region
  name       = "cors-preflight"
  # Official Caddy image through the dockerhub proxy repo. It has no entrypoint, so the command is needed.
  image   = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.dockerhub.repository_id}/library/caddy:2.11.9"
  command = ["caddy"]
  args = [
    "respond", "--listen", ":8080", "--status", "204",
    "--header", "Access-Control-Allow-Origin: *",
    "--header", "Access-Control-Allow-Methods: GET, POST, OPTIONS",
    "--header", "Access-Control-Allow-Headers: content-type, x-api-key, authorization",
    "--header", "Access-Control-Max-Age: 600",
  ]
  cpu           = "1"
  memory        = "256Mi"
  concurrency   = 80
  max_instances = 2
  invokers      = [] # each deployment adds its gateway service account

  depends_on = [google_project_service.apis, google_artifact_registry_repository.dockerhub]
}
