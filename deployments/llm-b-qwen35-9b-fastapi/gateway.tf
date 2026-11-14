# Public API Gateway in front of the private Vertex AI endpoint. The gateway checks the API key,
# so a request without a valid key never starts a replica.
# The gateway calls the CORS proxy (cors_proxy.tf) with a Google ID token of the gateway SA. The proxy calls
# Vertex AI :invoke with an access token and adds the CORS headers that Vertex AI does not send.
# No streaming: app.py answers in one JSON body.

locals {
  # Gateway ID and API ID. The API itself and the shared API key are in infra/core/gateways.tf (local.gateway_apis).
  # Max 27 chars: the gateway SA ID is "<gateway_id>-gw" (max 30).
  gateway_id = "llm-b-qwen35-fastapi"

  # The app.py routes that the gateway lets through. /health stays private.
  routes = {
    "/generate" = "generate"
    "/extract"  = "extract"
  }

  # OpenAPI 2.0. Only the listed paths reach the endpoint. Every path needs the API key.
  openapi = {
    swagger  = "2.0"
    info     = { title = local.gateway_id, version = "1.0.0" }
    schemes  = ["https"]
    produces = ["application/json"]
    x-google-backend = {
      # The CORS proxy (cors_proxy.tf) answers every call and OPTIONS, and forwards the POST to <endpoint>/invoke<path>.
      address          = module.cors_proxy.url
      path_translation = "APPEND_PATH_TO_ADDRESS"
      # The limit for the whole response. At 0 replicas, Vertex AI returns 429 at once (no wait for the cold start).
      deadline = 300.0
    }
    securityDefinitions = {
      api_key = { type = "apiKey", name = "x-api-key", in = "header" }
    }
    security = [{ api_key = [] }]
    # options: the browser CORS preflight of the test UI. It has no API key, so it has security = [].
    # The CORS proxy answers it.
    paths = {
      for path, op in local.routes : path => {
        post = { operationId = op, responses = { "200" = { description = "JSON answer of app.py" } } }
        options = {
          operationId = "${op}Cors"
          security    = []
          responses   = { "200" = { description = "CORS preflight" } }
        }
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

resource "google_api_gateway_gateway" "this" {
  provider   = google-beta
  project    = var.project_id
  region     = var.gateway_region
  gateway_id = local.gateway_id
  api_config = google_api_gateway_api_config.this.id

  depends_on = [module.cors_proxy]
}
