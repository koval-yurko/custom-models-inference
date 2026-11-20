mock_provider "google" {}

variables {
  project_id           = "p"
  title                = "Model T"
  resource_filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"svc\""
  ready_text           = "STARTUP HTTP probe succeeded"
  notification_channel = "projects/p/notificationChannels/1"
}

run "two_policies_with_filters" {
  command = apply

  assert {
    condition     = output.filters.ready == "${var.resource_filter} AND (textPayload:\"STARTUP HTTP probe succeeded\" OR jsonPayload.message:\"STARTUP HTTP probe succeeded\")"
    error_message = "the ready filter must be the resource filter plus the text in textPayload or jsonPayload.message"
  }
  assert {
    condition     = strcontains(output.filters.down, "Application shutdown complete.")
    error_message = "the down filter must use the uvicorn shutdown line by default"
  }
  assert {
    condition     = google_monitoring_alert_policy.this["ready"].conditions[0].condition_matched_log[0].filter == output.filters.ready
    error_message = "the ready policy must use the ready filter"
  }
  assert {
    condition     = google_monitoring_alert_policy.this["down"].conditions[0].condition_matched_log[0].filter == output.filters.down
    error_message = "the down policy must use the down filter"
  }
  assert {
    condition     = google_monitoring_alert_policy.this["ready"].documentation[0].subject == "🟢 Model T is ready"
    error_message = "wrong ready message"
  }
  assert {
    condition     = google_monitoring_alert_policy.this["down"].documentation[0].subject == "⚪ Model T scaled to 0"
    error_message = "wrong down message"
  }
}

run "strategy_and_channel" {
  command = apply

  assert {
    condition     = alltrue([for p in google_monitoring_alert_policy.this : p.notification_channels == tolist(["projects/p/notificationChannels/1"])])
    error_message = "both policies must notify the Slack channel"
  }
  assert {
    condition     = alltrue([for p in google_monitoring_alert_policy.this : p.alert_strategy[0].notification_rate_limit[0].period == "300s"])
    error_message = "log-based alerts need a rate limit; 300s is the minimum"
  }
  assert {
    condition     = alltrue([for p in google_monitoring_alert_policy.this : p.alert_strategy[0].auto_close == "1800s"])
    error_message = "incidents must close after 30 min"
  }
  assert {
    condition     = alltrue([for p in google_monitoring_alert_policy.this : p.alert_strategy[0].notification_prompts == tolist(["OPENED"])])
    error_message = "Slack must get no 'incident closed' message"
  }
}

run "rejects_quote_in_text" {
  command = plan

  variables {
    ready_text = "a\"b"
  }

  expect_failures = [var.ready_text]
}

run "rejects_empty_resource_filter" {
  command = plan

  variables {
    resource_filter = ""
  }

  expect_failures = [var.resource_filter]
}
