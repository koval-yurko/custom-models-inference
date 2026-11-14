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
    condition     = alltrue([for p in values(local.openapi.paths) : p.options.security == [] && !contains(keys(p.post), "security")])
    error_message = "only the OPTIONS (CORS preflight) operations may override the global security"
  }
  assert {
    condition     = join(",", sort(keys(local.openapi.paths))) == "/extract,/generate"
    error_message = "the gateway must expose only /generate and /extract (/health stays private)"
  }
  assert {
    condition     = local.openapi["x-google-backend"].address == module.cors_proxy.url && local.openapi["x-google-backend"].path_translation == "APPEND_PATH_TO_ADDRESS"
    error_message = "the gateway must call the CORS proxy and append the path (the proxy forwards it to :invoke)"
  }
  assert {
    condition     = length(google_service_account.gateway.account_id) <= 30
    error_message = "the gateway SA ID must be 30 chars or less"
  }
}
