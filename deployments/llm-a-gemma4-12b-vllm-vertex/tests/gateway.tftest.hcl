mock_provider "google" {
  # The gateway module needs an https backend URL.
  mock_resource "google_cloud_run_v2_service" {
    defaults = { uri = "https://proxy" }
  }
}
mock_provider "google-beta" {}

variables {
  project_id = "p"
}

run "gateway_requires_api_key" {
  command = apply

  override_data {
    target = data.google_monitoring_notification_channel.slack
    values = { name = "projects/p/notificationChannels/1" }
  }

  assert {
    condition     = module.model.openapi.security == [{ api_key = [] }]
    error_message = "every path must need the api_key"
  }
  assert {
    condition     = module.model.openapi.securityDefinitions.api_key == { type = "apiKey", name = "x-api-key", in = "header" }
    error_message = "the API key must come from the x-api-key header"
  }
  assert {
    condition     = alltrue(flatten([for p in values(module.model.openapi.paths) : [for m, op in p : m == "options" || !contains(keys(op), "security")]]))
    error_message = "only the OPTIONS (CORS preflight) operations may override the global security"
  }
  assert {
    condition     = alltrue([for p in values(module.model.openapi.paths) : p.options.security == []])
    error_message = "every path needs an OPTIONS operation without the API key, for the browser CORS preflight"
  }
  assert {
    condition     = keys(module.model.openapi.paths) == ["/v1/chat/completions", "/vertex/v1/chat/completions"]
    error_message = "the gateway must expose only the chat route: the old path and the vertex path (rawPredict reaches only predict_route)"
  }
  assert {
    condition     = alltrue([for p in values(module.model.openapi.paths) : p.post["x-google-backend"].address == "https://proxy" && p.post["x-google-backend"].path_translation == "APPEND_PATH_TO_ADDRESS"])
    error_message = "the gateway must call the CORS proxy (it adds the CORS headers) and pass the path (it picks the platform)"
  }
}

run "service_accounts" {
  command = apply

  override_data {
    target = data.google_monitoring_notification_channel.slack
    values = { name = "projects/p/notificationChannels/1" }
  }

  assert {
    condition     = length("${module.model.gateway_id}-gw") <= 30
    error_message = "the gateway SA ID must be 30 chars or less"
  }
}

run "outputs_for_scripts" {
  command = apply

  override_data {
    target = data.google_monitoring_notification_channel.slack
    values = { name = "projects/p/notificationChannels/1" }
  }

  assert {
    condition     = output.gateway_address == "module.model.module.gateway.google_api_gateway_gateway.this"
    error_message = "gateway-streaming.py imports the gateway at this address"
  }
  assert {
    condition     = output.platforms == tolist(["vertex"])
    error_message = "LLM-A runs on vertex only in phase 1"
  }
  assert {
    condition     = output.vertex.name == "llm-a-gemma4-12b-vllm-vertex" && output.gateway_id == "llm-a-gemma4-vertex"
    error_message = "the Vertex AI name and the gateway ID must stay"
  }
  assert {
    condition     = output.ui.base_url == "${output.gateway_url}/vertex" && output.ui.id == "llm-a-gemma4-vertex"
    error_message = "the ui base_url is the default platform path"
  }
  assert {
    condition     = length(output.ui.platforms) == 1 && output.ui.platforms[0].id == "vertex" && !contains(keys(output.ui.features), "cold_start")
    error_message = "cold_start moves from features into each platform entry"
  }
}
