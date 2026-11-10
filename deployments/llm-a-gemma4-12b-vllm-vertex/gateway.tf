# Public API Gateway in front of the private Vertex AI endpoint. The gateway checks the API key,
# so a request without a valid key never starts a replica.
# NOT VERIFIED: API Gateway calls the backend with a Google ID token of the gateway SA. Vertex AI may
# accept only OAuth access tokens. If the first call through the gateway returns 401, Vertex AI rejects
# the ID token: then put a small token proxy on Cloud Run between the gateway and the endpoint (see README).
# Streaming: the provider has no field for it. Run scripts/gateway-streaming.py after apply (see README).

locals {
  # Gateway ID and API ID. The API itself and the shared API key are in infra/core/gateways.tf (local.gateway_apis).
  # Max 27 chars: the gateway SA ID is "<gateway_id>-gw" (max 30).
  gateway_id = "llm-a-gemma4-vertex"

  # OpenAPI 2.0. Only the listed path reaches the endpoint. Every path needs the API key.
  openapi = {
    swagger  = "2.0"
    info     = { title = local.gateway_id, version = "1.0.0" }
    schemes  = ["https"]
    produces = ["application/json"]
    x-google-backend = {
      # :rawPredict forwards the body unchanged to the container predict_route (/v1/chat/completions).
      address          = "https://${module.model.endpoint_dns}/v1/projects/${var.project_id}/locations/${var.region}/endpoints/${module.model.endpoint_id}:rawPredict"
      path_translation = "CONSTANT_ADDRESS"
      # The limit for the whole response. At 0 replicas, Vertex AI returns 429 at once (no wait for the cold start).
      deadline = 300.0
    }
    securityDefinitions = {
      api_key = { type = "apiKey", name = "x-api-key", in = "header" }
    }
    security = [{ api_key = [] }]
    paths = {
      "/v1/chat/completions" = {
        post = { operationId = "chatCompletions", responses = { "200" = { description = "Chat completion" } } }
      }
    }
  }
}

resource "google_service_account" "gateway" {
  project      = var.project_id
  account_id   = "${local.gateway_id}-gw"
  display_name = "API Gateway for ${local.gateway_id}"
}

# The provider has no IAM resource for 1 Vertex AI endpoint, so the role is on the project.
# The member is the gateway SA of this deployment only, so destroy removes only this binding.
resource "google_project_iam_member" "gateway_predict" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.gateway.email}"
}

resource "google_api_gateway_api_config" "this" {
  provider             = google-beta
  project              = var.project_id
  api                  = local.gateway_id # made by infra/core/gateways.tf
  api_config_id_prefix = "${local.gateway_id}-"

  openapi_documents {
    document {
      path     = "openapi.yaml"
      contents = base64encode(yamlencode(local.openapi))
    }
  }

  gateway_config {
    backend_config {
      google_service_account = google_service_account.gateway.email
    }
  }

  # A config cannot change in place: make the new one before the gateway leaves the old one.
  lifecycle {
    create_before_destroy = true
  }
}

# Terraform creates this gateway without streaming. scripts/gateway-streaming.py replaces it with a
# streaming gateway that has the same ID, so this state entry stays valid.
resource "google_api_gateway_gateway" "this" {
  provider   = google-beta
  project    = var.project_id
  region     = var.gateway_region
  gateway_id = local.gateway_id
  api_config = google_api_gateway_api_config.this.id

  depends_on = [google_project_iam_member.gateway_predict]
}
