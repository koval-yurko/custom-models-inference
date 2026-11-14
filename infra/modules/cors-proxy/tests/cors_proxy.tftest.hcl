mock_provider "google" {}

variables {
  project_id                    = "p"
  region                        = "us-central1"
  name                          = "x-proxy"
  target                        = "https://dns/v1/projects/p/locations/us-central1/endpoints/1:rawPredict"
  gateway_service_account_email = "gw@p.iam.gserviceaccount.com"
  image                         = "us-central1-docker.pkg.dev/p/dockerhub/library/python:3.13.9-slim"
}

run "only_gateway_calls_and_proxy_predicts" {
  command = apply

  assert {
    condition     = google_cloud_run_v2_service_iam_member.gateway_invoker.member == "serviceAccount:gw@p.iam.gserviceaccount.com" && google_cloud_run_v2_service_iam_member.gateway_invoker.role == "roles/run.invoker"
    error_message = "only the gateway SA may call the proxy"
  }
  assert {
    condition     = google_project_iam_member.predict.role == "roles/aiplatform.user" && google_project_iam_member.predict.member == "serviceAccount:${module.service.service_account_email}"
    error_message = "only the proxy SA gets aiplatform.user"
  }
}

run "target_must_be_https" {
  command = plan
  variables {
    target = "http://dns/x"
  }
  expect_failures = [var.target]
}
