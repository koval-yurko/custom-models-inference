mock_provider "google" {
  # The gateway module needs an https backend URL.
  mock_resource "google_cloud_run_v2_service" {
    defaults = { uri = "https://proxy" }
  }
}
mock_provider "google-beta" {}
mock_provider "runpod" {
  mock_resource "runpod_serverless_endpoint" {
    defaults = { request_urls = { base = "https://ep1.api.runpod.ai" } }
  }
}

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
    condition     = keys(module.model.openapi.paths) == ["/runpod/v1/chat/completions", "/v1/chat/completions", "/vertex/v1/chat/completions"]
    error_message = "the gateway must expose only the chat route: the old path, the vertex path and the runpod path"
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
    condition     = output.platforms == tolist(["vertex", "runpod"])
    error_message = "LLM-A runs on vertex (default) and runpod"
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
    condition     = length(output.ui.platforms) == 2 && output.ui.platforms[0].id == "vertex" && output.ui.platforms[1].id == "runpod" && !contains(keys(output.ui.features), "cold_start")
    error_message = "cold_start moves from features into each platform entry"
  }
}

run "runpod_flags" {
  command = apply

  override_data {
    target = data.google_monitoring_notification_channel.slack
    values = { name = "projects/p/notificationChannels/1" }
  }

  assert {
    condition     = !strcontains(module.model.runpod_args, "--kv-cache-dtype") && !strcontains(module.model.runpod_args, "runai_streamer")
    error_message = "Runpod gives Ampere GPUs (no FP8) and has no GCS weights: no vertex-only flags"
  }
  assert {
    condition     = strcontains(module.model.runpod_args, "--revision=1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee") && strcontains(module.model.runpod_args, "--model=google/gemma-4-12B-it-qat-w4a16-ct")
    error_message = "Runpod downloads the pinned Hugging Face commit"
  }
}
