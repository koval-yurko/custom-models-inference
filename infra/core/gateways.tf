# API Gateway APIs and the one shared API key for all of them.
# The API (and its managed service) is made here, so the key can target it in the same apply.
# Each deployment makes its own API config and gateway on top of the API (see deployments/tts-a-kokoro-cpu/gateway.tf).

locals {
  # One entry per deployment with a gateway. The value is the API ID: the deployment uses the same ID.
  # Add a line here and apply this root before you apply the new deployment.
  gateway_apis = [
    "tts-a-kokoro-cpu",
    "llm-a-gemma4-vertex",
  ]
}

resource "google_api_gateway_api" "this" {
  for_each = toset(local.gateway_apis)

  provider = google-beta
  project  = var.project_id
  api_id   = each.value

  depends_on = [google_project_service.apis]
}

# Order: API -> placeholder config -> service enabled -> key.
# A managed service can be enabled only after its API has a config, and the gateway needs it enabled.
# So each API gets a placeholder config here. No gateway uses it: the deployment makes its own
# config with the real backend.
resource "google_api_gateway_api_config" "placeholder" {
  for_each = google_api_gateway_api.this

  provider             = google-beta
  project              = var.project_id
  api                  = each.value.api_id
  api_config_id_prefix = "placeholder-"

  openapi_documents {
    document {
      path = "openapi.yaml"
      contents = base64encode(yamlencode({
        swagger             = "2.0"
        info                = { title = each.key, version = "0.0.0" }
        schemes             = ["https"]
        produces            = ["application/json"]
        x-google-backend    = { address = "https://placeholder.invalid" }
        securityDefinitions = { api_key = { type = "apiKey", name = "x-api-key", in = "header" } }
        security            = [{ api_key = [] }]
        paths               = { "/placeholder" = { get = { operationId = "placeholder", responses = { "200" = { description = "none" } } } } }
      }))
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_project_service" "gateway" {
  for_each = google_api_gateway_api.this

  project            = var.project_id
  service            = each.value.managed_service
  disable_on_destroy = false

  depends_on = [google_api_gateway_api_config.placeholder]
}

# One key for all gateways. It works only for the gateway APIs above, not for other Google APIs.
resource "google_apikeys_key" "gateways" {
  count = length(local.gateway_apis) > 0 ? 1 : 0

  project      = var.project_id
  name         = "models-gateways"
  display_name = "API key for the model gateways"

  restrictions {
    dynamic "api_targets" {
      for_each = google_project_service.gateway
      content {
        service = api_targets.value.service
      }
    }
  }
}
