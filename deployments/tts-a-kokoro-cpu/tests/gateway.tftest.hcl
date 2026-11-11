mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id    = "p"
  invoker_email = "a@b.c"
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
    condition     = local.openapi["x-google-backend"].deadline <= 300
    error_message = "deadline must not be longer than the Cloud Run timeout (300s)"
  }
}

run "gateway_sa_email_matches" {
  command = apply

  assert {
    condition     = google_service_account.gateway.account_id == split("@", local.gateway_sa)[0]
    error_message = "local.gateway_sa must match the gateway service account"
  }
}
