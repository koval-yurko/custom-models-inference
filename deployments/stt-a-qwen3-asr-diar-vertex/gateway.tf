# Public API Gateway in front of the private Vertex AI endpoint. The gateway checks the API key,
# so a request without a valid key never starts a replica.
# /v1beta/interactions: the gateway calls the CORS proxy (cors_proxy.tf) with a Google ID token of the gateway SA.
# The proxy calls Vertex AI :rawPredict with an access token and adds the CORS headers that Vertex AI does not send.
# /v1beta/uploads and /v1beta/files...: the gateway calls the STT API service (stt_api.tf). It answers OPTIONS and adds
# CORS headers itself.
# No streaming: the app answers in one JSON body.

locals {
  # Gateway ID and API ID. The API itself and the shared API key are in infra/core/gateways.tf (local.gateway_apis).
  # Max 27 chars: the gateway SA ID is "<gateway_id>-gw" (max 30).
  gateway_id = "stt-a-qwen3-asr-diar"

  # options: the browser CORS preflight of the test UI. It has no API key, so it has security = [].
  preflight = { security = [], responses = { "200" = { description = "CORS preflight" } } }

  # The STT API service (stt_api.tf). API Gateway reads x-google-backend at the top level or the operation level only,
  # so each operation of a files path carries it. transcribe waits for the GPU, the other routes answer at once.
  files_backend = {
    for d in [30, 300] : tostring(d) => {
      x-google-backend = { address = module.stt_api.url, path_translation = "APPEND_PATH_TO_ADDRESS", deadline = d }
    }
  }
  p_id      = { name = "id", in = "path", required = true, type = "string" }
  p_version = { name = "version_id", in = "path", required = true, type = "string" }
  ok        = { "200" = { description = "JSON answer of the STT API service" } }

  # OpenAPI 2.0. Only the listed paths are open. Every path needs the API key. /health stays private.
  openapi = {
    swagger  = "2.0"
    info     = { title = local.gateway_id, version = "1.0.0" }
    schemes  = ["https"]
    produces = ["application/json"]
    x-google-backend = {
      # The CORS proxy answers every call and OPTIONS, and forwards the POST to :rawPredict (1 fixed URL).
      address          = module.cors_proxy.url
      path_translation = "APPEND_PATH_TO_ADDRESS"
      # The limit for the whole response. A 30-minute file can take longer (the user accepts the risk, see the spec).
      deadline = 300.0
    }
    securityDefinitions = {
      api_key = { type = "apiKey", name = "x-api-key", in = "header" }
    }
    security = [{ api_key = [] }]
    paths = {
      "/v1beta/interactions" = {
        post    = { operationId = "interactions", responses = { "200" = { description = "Gemini Interactions answer" } } }
        options = merge(local.preflight, { operationId = "interactionsCors" })
      }
      "/v1beta/uploads" = {
        post    = merge(local.files_backend["30"], { operationId = "uploads", responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "uploadsCors" })
      }
      "/v1beta/files" = {
        get     = merge(local.files_backend["30"], { operationId = "listFiles", responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "listFilesCors" })
      }
      "/v1beta/files/{id}" = {
        get     = merge(local.files_backend["30"], { operationId = "getFile", parameters = [local.p_id], responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "getFileCors", parameters = [local.p_id] })
      }
      "/v1beta/files/{id}/transcribe" = {
        post    = merge(local.files_backend["300"], { operationId = "transcribe", parameters = [local.p_id], responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "transcribeCors", parameters = [local.p_id] })
      }
      "/v1beta/files/{id}/audio" = {
        get     = merge(local.files_backend["30"], { operationId = "getAudio", parameters = [local.p_id], responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "getAudioCors", parameters = [local.p_id] })
      }
      "/v1beta/files/{id}/versions/{version_id}/names" = {
        put     = merge(local.files_backend["30"], { operationId = "putNames", parameters = [local.p_id, local.p_version], responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "putNamesCors", parameters = [local.p_id, local.p_version] })
      }
      "/v1beta/files/{id}/reference" = {
        get     = merge(local.files_backend["30"], { operationId = "getReference", parameters = [local.p_id], responses = local.ok })
        put     = merge(local.files_backend["30"], { operationId = "putReference", parameters = [local.p_id], responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "referenceCors", parameters = [local.p_id] })
      }
      "/v1beta/files/{id}/versions/{version_id}/score" = {
        get     = merge(local.files_backend["30"], { operationId = "getScore", parameters = [local.p_id, local.p_version], responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "getScoreCors", parameters = [local.p_id, local.p_version] })
      }
      # Reads every version of every file with a reference, so it gets the long deadline.
      "/v1beta/scores" = {
        get     = merge(local.files_backend["300"], { operationId = "listScores", responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "listScoresCors" })
      }
      "/v1beta/files/{id}/versions/{version_id}" = {
        get     = merge(local.files_backend["30"], { operationId = "getVersion", parameters = [local.p_id, local.p_version], responses = local.ok })
        options = merge(local.preflight, local.files_backend["30"], { operationId = "getVersionCors", parameters = [local.p_id, local.p_version] })
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

  depends_on = [module.cors_proxy, module.stt_api]
}
