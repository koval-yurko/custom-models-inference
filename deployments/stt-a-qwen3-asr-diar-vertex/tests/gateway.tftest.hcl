mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "p"
}

run "gateway_requires_api_key" {
  command = apply

  assert {
    condition     = local.openapi.security == [{ api_key = [] }]
    error_message = "every path must need the api_key"
  }
  assert {
    condition     = alltrue([for p in values(local.openapi.paths) : alltrue([for m, op in p : m == "options" ? op.security == [] : !contains(keys(op), "security")])])
    error_message = "only the OPTIONS (CORS preflight) operations may override the global security"
  }
  assert {
    condition     = join(",", sort(keys(local.openapi.paths))) == "/v1beta/files,/v1beta/files/{id},/v1beta/files/{id}/transcribe,/v1beta/files/{id}/versions/{version_id},/v1beta/interactions,/v1beta/uploads"
    error_message = "the gateway must expose only the interactions, uploads and files paths (/health stays private)"
  }
  assert {
    condition = alltrue(flatten([for path, ops in local.openapi.paths : [
      for op in values(ops) : op["x-google-backend"].address == module.upload.url && op["x-google-backend"].path_translation == "APPEND_PATH_TO_ADDRESS"
    ] if path != "/v1beta/interactions"]))
    error_message = "every operation of the files service paths must carry its own backend (API Gateway ignores it on a path)"
  }
  assert {
    condition = (
      local.openapi.paths["/v1beta/files/{id}/transcribe"].post["x-google-backend"].deadline == 300
      && local.openapi.paths["/v1beta/files"].get["x-google-backend"].deadline == 30
      && local.openapi.paths["/v1beta/files/{id}"].get["x-google-backend"].deadline == 30
      && local.openapi.paths["/v1beta/files/{id}/versions/{version_id}"].get["x-google-backend"].deadline == 30
    )
    error_message = "transcribe waits up to 300 s, the other files routes 30 s"
  }
  assert {
    condition = alltrue([
      for op in values(local.openapi.paths["/v1beta/files/{id}/versions/{version_id}"]) :
      toset([for p in op.parameters : "${p.name}:${p["in"]}:${p.required}:${p.type}"]) == toset(["id:path:true:string", "version_id:path:true:string"])
    ])
    error_message = "the path parameters id and version_id must be declared on each operation"
  }
  assert {
    condition = alltrue([
      for path in ["/v1beta/files/{id}", "/v1beta/files/{id}/transcribe"] : alltrue([
        for op in values(local.openapi.paths[path]) : [for p in op.parameters : p.name] == ["id"]
      ])
    ])
    error_message = "the path parameter id must be declared on each operation that uses it"
  }
  assert {
    condition     = local.openapi["x-google-backend"].address == module.cors_proxy.url && local.openapi["x-google-backend"].deadline == 300
    error_message = "transcription calls go to the CORS proxy with the 300 s deadline"
  }
  assert {
    condition     = !contains(keys(local.openapi.paths["/v1beta/interactions"]), "x-google-backend")
    error_message = "/v1beta/interactions must use the global backend"
  }
  # API Gateway reads x-google-backend at the top level or the operation level, not at the path level.
  assert {
    condition = alltrue([for op in ["post", "options"] : (
      local.openapi.paths["/v1beta/uploads"][op]["x-google-backend"].address == module.upload.url
      && local.openapi.paths["/v1beta/uploads"][op]["x-google-backend"].path_translation == "APPEND_PATH_TO_ADDRESS"
      && local.openapi.paths["/v1beta/uploads"][op]["x-google-backend"].deadline == 30
    )])
    error_message = "both operations of /v1beta/uploads must go to the upload service with a 30 s deadline"
  }
  assert {
    condition     = !contains(keys(local.openapi.paths["/v1beta/uploads"]), "x-google-backend")
    error_message = "a path-level x-google-backend is ignored by API Gateway"
  }
  assert {
    condition     = length(google_service_account.gateway.account_id) <= 30
    error_message = "the gateway SA ID must be 30 chars or less"
  }
}
