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
    condition     = local.openapi.securityDefinitions.api_key == { type = "apiKey", name = "x-api-key", in = "header" }
    error_message = "the API key must come from the x-api-key header"
  }
  assert {
    condition     = alltrue(flatten([for p in values(local.openapi.paths) : [for m, op in p : m == "options" || !contains(keys(op), "security")]]))
    error_message = "only the OPTIONS (CORS preflight) operations may override the global security"
  }
  assert {
    condition     = alltrue([for p in values(local.openapi.paths) : p.options.security == []])
    error_message = "every path needs an OPTIONS operation without the API key, for the browser CORS preflight"
  }
  assert {
    condition     = keys(local.openapi.paths) == ["/v1/chat/completions"]
    error_message = "the gateway must expose only the chat route (rawPredict reaches only predict_route)"
  }
  assert {
    condition     = local.openapi["x-google-backend"].address == module.cors_proxy.url && local.openapi["x-google-backend"].path_translation == "CONSTANT_ADDRESS"
    error_message = "the gateway must call the CORS proxy (it adds the CORS headers), with a constant address"
  }
}

run "service_accounts" {
  command = apply

  assert {
    condition     = length(google_service_account.gateway.account_id) <= 30
    error_message = "the gateway SA ID must be 30 chars or less"
  }
}
