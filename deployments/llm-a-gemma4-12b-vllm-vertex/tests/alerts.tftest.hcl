mock_provider "google" {
  mock_resource "google_cloud_run_v2_service" {
    defaults = { uri = "https://proxy" }
  }
}
mock_provider "google-beta" {}
mock_provider "runpod" {
  mock_resource "runpod_serverless_endpoint" {
    defaults = { request_urls = { base = "https://ep1.api.runpod.ai" } }
  }
}

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
    condition     = strcontains(module.scale_alerts[0].filters.ready, "resource.labels.endpoint_id=\"${module.model.vertex_endpoint_id}\"")
    error_message = "the alerts must watch only this endpoint"
  }
  assert {
    condition     = strcontains(module.scale_alerts[0].filters.ready, "Application startup complete.")
    error_message = "ready must be the line Application startup complete."
  }
  assert {
    condition     = strcontains(module.scale_alerts[0].filters.down, "Application shutdown complete.")
    error_message = "the down alert must watch the uvicorn shutdown line"
  }
}

run "platform_alerts_watch_scale_watch_lines" {
  command = apply

  override_data {
    target = data.google_monitoring_notification_channel.slack
    values = { name = "projects/p/notificationChannels/1" }
  }

  assert {
    condition     = keys(module.platform_alerts) == ["runpod"]
    error_message = "1 alert pair per platform without GCP logs"
  }
  assert {
    condition     = strcontains(module.platform_alerts["runpod"].filters.ready, "resource.labels.job_name=\"scale-watch\"") && strcontains(module.platform_alerts["runpod"].filters.ready, "scale-watch: runpod ")
    error_message = "the Runpod ready alert matches the scale-watch line"
  }
  assert {
    condition     = strcontains(module.platform_alerts["runpod"].filters.down, "scale-watch: runpod ") && strcontains(module.platform_alerts["runpod"].filters.down, " scaled to 0")
    error_message = "the Runpod down alert matches the scaled to 0 line"
  }
}
