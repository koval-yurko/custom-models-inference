mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id    = "p"
  invoker_email = "a@b.c"
}

run "alerts_watch_own_model" {
  command = apply

  override_data {
    target = data.google_monitoring_notification_channel.slack
    values = { name = "projects/p/notificationChannels/1" }
  }

  assert {
    condition     = strcontains(module.scale_alerts.filters.ready, "resource.labels.service_name=\"tts-a-kokoro-cpu\"")
    error_message = "the alerts must watch only this Cloud Run service"
  }
  assert {
    condition     = strcontains(module.scale_alerts.filters.ready, "STARTUP HTTP probe succeeded")
    error_message = "ready must be the startup probe line: uvicorn logs startup complete before the probe passes"
  }
  assert {
    condition     = strcontains(module.scale_alerts.filters.down, "Application shutdown complete.")
    error_message = "the down alert must watch the uvicorn shutdown line"
  }
}
