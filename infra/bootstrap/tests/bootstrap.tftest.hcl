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
