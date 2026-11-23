mock_provider "google" {
  # The gateway module needs an https backend URL.
  mock_resource "google_cloud_run_v2_service" {
    defaults = { uri = "https://svc" }
  }
}
mock_provider "google-beta" {}
mock_provider "runpod" {
  mock_resource "runpod_serverless_endpoint" {
    defaults = { request_urls = { base = "https://ep1.api.runpod.ai" } }
  }
  mock_resource "runpod_network_volume" {
    defaults = { id = "vol1" }
  }
}

# The registry credential of infra/core, found by name. The mock provider cannot fill the data source.
override_module {
  target  = module.model.module.runpod[0].module.registry[0]
  outputs = { id = "reg1" }
}

override_data {
  target = data.google_monitoring_notification_channel.slack
  values = { name = "projects/p/notificationChannels/1" }
}

variables {
  project_id = "p"
}

run "gateway_requires_api_key" {
  command = apply

  assert {
    condition     = module.model.openapi.security == [{ api_key = [] }]
    error_message = "every path must need the api_key"
  }
  assert {
    condition     = alltrue([for p in values(module.model.openapi.paths) : alltrue([for m, op in p : m == "options" ? op.security == [] : !contains(keys(op), "security")])])
    error_message = "only the OPTIONS (CORS preflight) operations may override the global security"
  }
  assert {
    condition     = toset(keys(module.model.openapi.paths)) == toset(flatten([for prefix in ["", "/vertex", "/runpod"] : ["${prefix}/generate", "${prefix}/extract"]]))
    error_message = "the gateway exposes /generate and /extract, the old paths and /vertex/ and /runpod/ (/health stays private)"
  }
  assert {
    condition = alltrue(flatten([for ops in values(module.model.openapi.paths) : [
      for op in values(ops) : op["x-google-backend"].address == module.model.proxy_url && op["x-google-backend"].path_translation == "APPEND_PATH_TO_ADDRESS" && op["x-google-backend"].deadline == 300
    ]]))
    error_message = "every operation calls the CORS proxy, appends the path and waits up to 300 s"
  }
  assert {
    condition     = module.model.gateway_id == "llm-b-qwen35-fastapi"
    error_message = "the gateway ID stays (the API in infra/core/gateways.tf, moved.tf keeps the gateway)"
  }
}
