mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "p"
}

run "alerts_watch_own_model" {
  command = apply

  override_data {
    target = data.google_monitoring_notification_channel.slack
    values = { name = "projects/p/notificationChannels/1" }
  }

  assert {
    condition     = strcontains(module.scale_alerts.filters.ready, "resource.labels.endpoint_id=\"${module.model.endpoint_id}\"")
    error_message = "the alerts must watch only this endpoint"
  }
  assert {
    condition     = strcontains(module.scale_alerts.filters.ready, "models ready")
    error_message = "ready must be the line models ready (speech_engine/main.py prints it after the 3 models load)"
  }
  assert {
    condition     = strcontains(module.scale_alerts.filters.down, "Application shutdown complete.")
    error_message = "the down alert must watch the uvicorn shutdown line"
  }
}
