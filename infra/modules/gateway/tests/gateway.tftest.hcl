mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id  = "p"
  region      = "us-central1"
  gateway_id  = "llm-a-gemma4-vertex"
  backend_url = "https://proxy"
  platforms   = ["vertex"]
  routes      = ["/v1/chat/completions"]
  deadlines   = { vertex = 300 }
}

run "paths_per_platform_plus_old" {
  command = apply

  assert {
    condition     = keys(output.openapi.paths) == ["/v1/chat/completions", "/vertex/v1/chat/completions"]
    error_message = "each route needs the old path and one path per platform"
  }
}

run "every_operation_calls_backend_with_append" {
  command = apply

  assert {
    condition     = alltrue(flatten([for p in values(output.openapi.paths) : [for m, op in p : op["x-google-backend"].address == "https://proxy" && op["x-google-backend"].path_translation == "APPEND_PATH_TO_ADDRESS" && op["x-google-backend"].deadline == 300]]))
    error_message = "every operation must call the backend with APPEND_PATH_TO_ADDRESS and the platform deadline"
  }
  assert {
    condition     = !contains(keys(output.openapi), "x-google-backend")
    error_message = "no top-level x-google-backend: each operation has its own"
  }
}

run "api_key_and_cors_preflight" {
  command = apply

  assert {
    condition     = output.openapi.security == [{ api_key = [] }]
    error_message = "every path must need the api_key"
  }
  assert {
    condition     = output.openapi.securityDefinitions.api_key == { type = "apiKey", name = "x-api-key", in = "header" }
    error_message = "the API key must come from the x-api-key header"
  }
  assert {
    condition     = alltrue(flatten([for p in values(output.openapi.paths) : [for m, op in p : m == "options" || !contains(keys(op), "security")]]))
    error_message = "only the OPTIONS (CORS preflight) operations may override the global security"
  }
  assert {
    condition     = alltrue([for p in values(output.openapi.paths) : p.options.security == []])
    error_message = "every path needs an OPTIONS operation without the API key, for the browser CORS preflight"
  }
}

run "operation_ids_unique" {
  command = apply

  variables {
    platforms   = ["vertex", "runpod"]
    deadlines   = { vertex = 300, runpod = 1200 }
    routes      = ["/v1/chat/completions", "/v1/models"]
    extra_paths = { "/v1beta/files" = { backend_url = "https://api", methods = ["get", "post"], deadline = 60 } }
  }

  assert {
    condition     = length(distinct(flatten([for p in values(output.openapi.paths) : [for op in values(p) : op.operationId]]))) == length(flatten([for p in values(output.openapi.paths) : [for op in values(p) : op.operationId]]))
    error_message = "operationId values must be unique"
  }
}

run "deadline_per_platform" {
  command = apply

  variables {
    platforms = ["vertex", "runpod"]
    deadlines = { vertex = 300, runpod = 1200 }
  }

  assert {
    condition     = output.openapi.paths["/runpod/v1/chat/completions"].post["x-google-backend"].deadline == 1200
    error_message = "a platform path uses the deadline of its platform"
  }
  assert {
    condition     = output.openapi.paths["/v1/chat/completions"].post["x-google-backend"].deadline == 300
    error_message = "the old path uses the deadline of the default (first) platform"
  }
}

run "extra_paths_get_prefix_and_own_backend" {
  command = apply

  variables {
    extra_paths = { "/v1beta/files" = { backend_url = "https://api", methods = ["get"], deadline = 60 } }
  }

  assert {
    condition     = alltrue([for k in ["/v1beta/files", "/vertex/v1beta/files"] : keys(output.openapi.paths[k]) == ["get", "options"]])
    error_message = "an extra path gets the old path and a prefixed path, each with its methods and options"
  }
  assert {
    condition     = alltrue([for k in ["/v1beta/files", "/vertex/v1beta/files"] : output.openapi.paths[k].get["x-google-backend"].address == "https://api" && output.openapi.paths[k].get["x-google-backend"].deadline == 60])
    error_message = "an extra path goes to its own backend"
  }
}

run "sa_id_max_30" {
  command = apply

  assert {
    condition     = length(google_service_account.this.account_id) <= 30
    error_message = "the gateway SA ID must be 30 chars or less"
  }
  assert {
    condition     = output.address == "google_api_gateway_gateway.this" && output.gateway_url == "https://${google_api_gateway_gateway.this.default_hostname}"
    error_message = "outputs for scripts"
  }
}

run "gateway_id_max_27" {
  command = plan

  variables {
    gateway_id = "a-gateway-id-that-is-too-long"
  }
  expect_failures = [var.gateway_id]
}
