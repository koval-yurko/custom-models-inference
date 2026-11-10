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
    condition     = alltrue(flatten([for p in values(local.openapi.paths) : [for op in values(p) : !contains(keys(op), "security")]]))
    error_message = "no operation may override the global security"
  }
  assert {
    condition     = keys(local.openapi.paths) == ["/v1/chat/completions"]
    error_message = "the gateway must expose only the chat route (rawPredict reaches only predict_route)"
  }
  assert {
    condition     = endswith(local.openapi["x-google-backend"].address, ":rawPredict") && local.openapi["x-google-backend"].path_translation == "CONSTANT_ADDRESS"
    error_message = "the backend must be the endpoint rawPredict URL with a constant address"
  }
}

run "gateway_sa_can_predict" {
  command = apply

  assert {
    condition     = length(google_service_account.gateway.account_id) <= 30
    error_message = "the gateway SA ID must be 30 chars or less"
  }
  assert {
    condition     = google_project_iam_member.gateway_predict.member == "serviceAccount:${google_service_account.gateway.email}" && google_project_iam_member.gateway_predict.role == "roles/aiplatform.user"
    error_message = "only the gateway SA gets aiplatform.user"
  }
}
