mock_provider "google" {}
mock_provider "google-beta" {
  mock_resource "google_api_gateway_api" {
    defaults = { managed_service = "tts-a-kokoro-cpu-abc.apigateway.p.cloud.goog" }
  }
}

variables {
  project_id      = "p"
  billing_account = "000000-000000-000000"
  hf_token        = "test"
}

run "shared_key_targets_only_the_gateway_apis" {
  command = apply

  assert {
    condition     = length(google_apikeys_key.gateways) == 1 && length(google_apikeys_key.gateways[0].restrictions) == 1
    error_message = "there must be one restricted key"
  }
  assert {
    condition = (
      toset([for t in google_apikeys_key.gateways[0].restrictions[0].api_targets : t.service])
      == toset([for a in google_api_gateway_api.this : a.managed_service])
    )
    error_message = "the key must target exactly the managed services of the gateway APIs"
  }
  assert {
    condition     = keys(google_api_gateway_api_config.placeholder) == keys(google_api_gateway_api.this)
    error_message = "every gateway API must have a placeholder config, so its managed service is on"
  }
  assert {
    condition     = keys(google_project_service.gateway) == keys(google_api_gateway_api.this)
    error_message = "every gateway API must have its managed service enabled"
  }
}
