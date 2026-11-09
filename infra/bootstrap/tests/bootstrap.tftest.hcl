mock_provider "google" {}

variables {
  project_id      = "p"
  billing_account = "000000-000000-000000"
}

run "enables_apis_needed_by_first_apply" {
  command = plan

  assert {
    condition     = contains(keys(google_project_service.apis), "cloudresourcemanager.googleapis.com")
    error_message = "data.google_project needs the Cloud Resource Manager API"
  }
  assert {
    condition     = contains(keys(google_project_service.apis), "serviceusage.googleapis.com")
    error_message = "google_project_service needs the Service Usage API"
  }
}

run "budget_uses_budget_amount" {
  command = plan

  variables {
    budget_amount = 35
  }

  assert {
    condition     = google_billing_budget.monthly.amount[0].specified_amount[0].units == "35"
    error_message = "budget amount must come from var.budget_amount"
  }
}

run "rejects_non_integer_budget" {
  command = plan

  variables {
    budget_amount = 20.5
  }

  expect_failures = [var.budget_amount]
}

run "weights_copy_job" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_job.weights_copy.template[0].template[0].volumes[0].gcs[0].bucket == "p-models"
    error_message = "job must mount the weights bucket"
  }
  assert {
    condition     = google_cloud_run_v2_job.weights_copy.template[0].template[0].volumes[0].gcs[0].read_only == false
    error_message = "job must write to the bucket"
  }
  assert {
    condition     = one([for e in google_cloud_run_v2_job.weights_copy.template[0].template[0].containers[0].env : e.value_source[0].secret_key_ref[0].secret if e.name == "HF_TOKEN"]) == "hf-token"
    error_message = "HF_TOKEN must come from the hf-token secret"
  }
  assert {
    condition     = google_storage_bucket_iam_member.weights_copy.role == "roles/storage.objectAdmin" && google_secret_manager_secret_iam_member.weights_copy.role == "roles/secretmanager.secretAccessor"
    error_message = "job SA needs objectAdmin on the bucket and secretAccessor on the token"
  }
}
