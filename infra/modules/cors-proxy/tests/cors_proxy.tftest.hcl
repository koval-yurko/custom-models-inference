mock_provider "google" {}

variables {
  project_id = "p"
  region     = "us-central1"
  name       = "x-proxy"
  targets = {
    vertex = { url = "https://dns/v1/projects/p/locations/us-central1/endpoints/1:rawPredict", append_path = false, auth = "google" }
  }
  default_platform              = "vertex"
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
    condition     = google_project_iam_member.predict[0].role == "roles/aiplatform.user" && google_project_iam_member.predict[0].member == "serviceAccount:${module.service.service_account_email}"
    error_message = "only the proxy SA gets aiplatform.user"
  }
  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.extra_invoker) == 0
    error_message = "no extra invokers by default"
  }
  assert {
    condition     = jsondecode(output.env.TARGETS).vertex.append_path == false && output.env.DEFAULT == "vertex"
    error_message = "the proxy env must hold TARGETS and DEFAULT"
  }
}

run "targets_must_be_https" {
  command = plan
  variables {
    targets = { vertex = { url = "http://dns/x", append_path = false, auth = "google" } }
  }
  expect_failures = [var.targets]
}

run "auth_must_be_known" {
  command = plan
  variables {
    targets = { vertex = { url = "https://dns/x", append_path = false, auth = "aws" } }
  }
  expect_failures = [var.targets]
}

run "default_must_be_a_target" {
  command = plan
  variables {
    default_platform = "x"
  }
  expect_failures = [var.default_platform]
}

run "no_predict_role_without_google_target" {
  command = apply
  variables {
    targets          = { runpod = { url = "https://r", append_path = true, auth = "runpod" } }
    default_platform = "runpod"
    secret_env       = { RUNPOD_API_KEY = "runpod-api-key" }
  }

  assert {
    condition     = length(google_project_iam_member.predict) == 0
    error_message = "no aiplatform.user without a google target"
  }
}

run "extra_invokers_may_call" {
  command = apply

  variables {
    extra_invokers = ["api@p.iam.gserviceaccount.com"]
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.extra_invoker[0].member == "serviceAccount:api@p.iam.gserviceaccount.com" && google_cloud_run_v2_service_iam_member.extra_invoker[0].role == "roles/run.invoker"
    error_message = "an extra invoker gets roles/run.invoker on the proxy"
  }
}
