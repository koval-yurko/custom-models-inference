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
  project_id      = "p"
  modal_workspace = "ws"
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
    condition = toset(keys(module.model.openapi.paths)) == toset(flatten([for prefix in ["", "/modal", "/vertex", "/runpod"] : [
      for p in ["/v1beta/files", "/v1beta/files/{id}", "/v1beta/files/{id}/audio", "/v1beta/files/{id}/reference", "/v1beta/files/{id}/transcribe", "/v1beta/files/{id}/versions/{version_id}", "/v1beta/files/{id}/versions/{version_id}/names", "/v1beta/files/{id}/versions/{version_id}/score", "/v1beta/interactions", "/v1beta/scores", "/v1beta/uploads"] : "${prefix}${p}"
    ]]))
    error_message = "the gateway exposes the interactions and files paths, the old ones and /vertex/ and /runpod/ (/health stays private)"
  }
  assert {
    condition = alltrue(flatten([for path, ops in module.model.openapi.paths : [
      for op in values(ops) : op["x-google-backend"].address == module.stt_api.url && op["x-google-backend"].path_translation == "APPEND_PATH_TO_ADDRESS"
    ] if !endswith(path, "/v1beta/interactions")]))
    error_message = "every operation of the STT API service paths must carry its own backend (API Gateway ignores it on a path)"
  }
  assert {
    condition = alltrue(flatten([for path in ["/v1beta/interactions", "/vertex/v1beta/interactions", "/runpod/v1beta/interactions"] : [
      for op in values(module.model.openapi.paths[path]) : op["x-google-backend"].address == module.model.proxy_url && op["x-google-backend"].deadline == 300
    ]]))
    error_message = "transcription calls go to the CORS proxy with the 300 s deadline"
  }
  assert {
    condition = alltrue([for prefix in ["", "/runpod"] : (
      module.model.openapi.paths["${prefix}/v1beta/files/{id}/transcribe"].post["x-google-backend"].deadline == 300
      && module.model.openapi.paths["${prefix}/v1beta/scores"].get["x-google-backend"].deadline == 300
      && module.model.openapi.paths["${prefix}/v1beta/files"].get["x-google-backend"].deadline == 30
      && module.model.openapi.paths["${prefix}/v1beta/uploads"].post["x-google-backend"].deadline == 30
      && module.model.openapi.paths["${prefix}/v1beta/files/{id}/reference"].put["x-google-backend"].deadline == 30
    )])
    error_message = "transcribe and scores wait up to 300 s, the other files routes 30 s"
  }
  assert {
    condition = alltrue([
      for op in concat(values(module.model.openapi.paths["/v1beta/files/{id}/versions/{version_id}"]), values(module.model.openapi.paths["/runpod/v1beta/files/{id}/versions/{version_id}/score"])) :
      toset([for p in op.parameters : "${p.name}:${p["in"]}:${p.required}:${p.type}"]) == toset(["id:path:true:string", "version_id:path:true:string"])
    ])
    error_message = "the path parameters id and version_id must be declared on each operation"
  }
  assert {
    condition = alltrue([
      for path in ["/v1beta/files/{id}", "/v1beta/files/{id}/transcribe", "/runpod/v1beta/files/{id}/audio", "/vertex/v1beta/files/{id}/reference"] : alltrue([
        for op in values(module.model.openapi.paths[path]) : [for p in op.parameters : p.name] == ["id"]
      ])
    ])
    error_message = "the path parameter id must be declared on each operation that uses it"
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.stt_api_gateway.member == "serviceAccount:${module.model.gateway_service_account_email}"
    error_message = "the gateway SA may call the STT API service"
  }
}
