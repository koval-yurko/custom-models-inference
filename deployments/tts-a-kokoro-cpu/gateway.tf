# Public API Gateway in front of the private Cloud Run service. The gateway checks the API key,
# so a request without a valid key never starts an instance.
# Streaming: the provider has no field for it. Run scripts/gateway-streaming.py after apply (see README).

locals {
  # Gateway ID and API ID. The API itself and the shared API key are in infra/core/gateways.tf (local.gateway_apis).
  gateway_id = "tts-a-kokoro-cpu"
  gateway_sa = "${local.gateway_id}-gw@${var.project_id}.iam.gserviceaccount.com"

  # OpenAPI 2.0. Only the listed paths reach the service. Every path needs the API key.
  openapi = {
    swagger  = "2.0"
    info     = { title = local.gateway_id, version = "1.0.0" }
    schemes  = ["https"]
    produces = ["application/json"]
    x-google-backend = {
      address          = module.service.url
      protocol         = "h2"
      path_translation = "APPEND_PATH_TO_ADDRESS"
      # Must not be longer than the Cloud Run request timeout (module default 300s). Includes the cold start.
      deadline = 300.0
    }
    securityDefinitions = {
      api_key = { type = "apiKey", name = "x-api-key", in = "header" }
    }
    security = [{ api_key = [] }]
    paths = {
      "/v1/audio/speech" = {
        post = { operationId = "speech", responses = { "200" = { description = "Audio" } } }
      }
      "/v1/audio/voices" = {
        get = { operationId = "voices", responses = { "200" = { description = "Voice list" } } }
      }
    }
  }
}

resource "google_service_account" "gateway" {
  project      = var.project_id
  account_id   = "${local.gateway_id}-gw"
  display_name = "API Gateway for ${local.gateway_id}"
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
}
