mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id      = "p"
  region          = "us-central1"
  billing_account = "000000-000000-000000"
  hf_token        = "test"
}

run "cors_preflight_service" {
  command = plan

  assert {
    condition     = module.cors_preflight.service_name == "cors-preflight"
    error_message = "deployments build the service URL from this name"
  }
  assert {
    condition     = startswith(google_artifact_registry_repository.dockerhub.repository_id, "dockerhub")
    error_message = "the image must come from the dockerhub proxy repo"
  }
}
