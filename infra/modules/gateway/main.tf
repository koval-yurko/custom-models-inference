# Public API Gateway for one model. The gateway checks the API key, so a request without a valid key never starts
# a replica. It calls the CORS proxy with a Google ID token of the gateway SA. The proxy picks the platform by the
# first path segment (/vertex/v1/...). The old paths without a prefix go to the default platform.
# Streaming: the provider has no field for it. Run scripts/gateway-streaming.py after apply.

locals {
  default = var.platforms[0]

  # One entry per OpenAPI path: the methods, the backend and the deadline. The old path uses the default platform.
  model_paths = merge(
    { for r in var.routes : r => { name = r, methods = var.methods, address = var.backend_url, deadline = var.deadlines[local.default] } },
    merge([for p in var.platforms : {
      for r in var.routes : "/${p}${r}" => { name = "${p} ${r}", methods = var.methods, address = var.backend_url, deadline = var.deadlines[p] }
    }]...),
  )
  extra = merge(
    { for k, e in var.extra_paths : k => { name = "extra ${k}", methods = e.methods, address = e.backend_url, deadline = e.deadline } },
    merge([for p in var.platforms : {
      for k, e in var.extra_paths : "/${p}${k}" => { name = "${p} extra ${k}", methods = e.methods, address = e.backend_url, deadline = e.deadline }
    }]...),
  )

  # Path parameters: each {name} in a path (STT-A /v1beta/files/{id}). A path without one gets no parameters key, so
  # the documents of the other models stay the same (no new API config).
  params = { for path in keys(merge(local.model_paths, local.extra)) : path => {
    for k, v in { parameters = [for n in flatten(regexall("{([A-Za-z0-9_]+)}", path)) : { name = n, in = "path", required = true, type = "string" }] } :
    k => v if length(v) > 0
  } }

  # OpenAPI 2.0. Only the listed paths reach the backends. Every path needs the API key.
  # x-google-backend is on each operation: API Gateway ignores it on a path.
  openapi = {
    swagger  = "2.0"
    info     = { title = var.gateway_id, version = "1.0.0" }
    schemes  = ["https"]
    produces = ["application/json"]
    securityDefinitions = {
      api_key = { type = "apiKey", name = "x-api-key", in = "header" }
    }
    security = [{ api_key = [] }]
    paths = { for path, e in merge(local.model_paths, local.extra) : path => merge(
      { for m in e.methods : m => merge(local.params[path], {
        operationId = replace(title(replace("${e.name} ${m}", "/[^a-zA-Z0-9]+/", " ")), " ", "")
        responses   = { "200" = { description = "OK" } }
        x-google-backend = {
          address          = e.address
          path_translation = "APPEND_PATH_TO_ADDRESS"
          # The limit for the whole response.
          deadline = e.deadline
        }
      }) },
      {
        # The browser CORS preflight of the test UI. It has no API key. The backend answers it.
        options = merge(local.params[path], {
          operationId = replace(title(replace("${e.name} cors", "/[^a-zA-Z0-9]+/", " ")), " ", "")
          security    = []
          responses   = { "200" = { description = "CORS preflight" } }
          x-google-backend = {
            address          = e.address
            path_translation = "APPEND_PATH_TO_ADDRESS"
            deadline         = e.deadline
          }
        })
      },
    ) }
  }
}

resource "google_service_account" "this" {
  project      = var.project_id
  account_id   = "${var.gateway_id}-gw"
  display_name = "API Gateway for ${var.gateway_id}"
}

resource "google_api_gateway_api_config" "this" {
  provider             = google-beta
  project              = var.project_id
  api                  = var.gateway_id # made by infra/core/gateways.tf
  api_config_id_prefix = "${var.gateway_id}-"

  openapi_documents {
    document {
      path     = "openapi.yaml"
      contents = base64encode(yamlencode(local.openapi))
    }
  }

  gateway_config {
    backend_config {
      google_service_account = google_service_account.this.email
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
  region     = var.region
  gateway_id = var.gateway_id
  api_config = google_api_gateway_api_config.this.id
}
