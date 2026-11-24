mock_provider "google" {
  # The gateway module needs an https backend URL.
  mock_resource "google_cloud_run_v2_service" {
    defaults = { uri = "https://svc" }
  }
}
mock_provider "google-beta" {}
mock_provider "runpod" {
  mock_resource "runpod_serverless_endpoint" {
    defaults = { request_urls = { base = "https://ep1.api.runpod.ai" } }
  }
  mock_resource "runpod_network_volume" {
    defaults = { id = "vol1" }
  }
}

# The registry credential of infra/core, found by name. The mock provider cannot fill the data source.
override_module {
  target  = module.model.module.runpod[0].module.registry[0]
  outputs = { id = "reg1" }
}

override_data {
  target = data.google_monitoring_notification_channel.slack
  values = { name = "projects/p/notificationChannels/1" }
}

variables {
  project_id = "p"
}

run "alerts_watch_own_model" {
  command = apply

  assert {
    condition     = strcontains(module.scale_alerts[0].filters.ready, "resource.labels.endpoint_id=\"${module.model.vertex_endpoint_id}\"")
    error_message = "the alerts must watch only this endpoint"
  }
  assert {
    condition     = strcontains(module.scale_alerts[0].filters.ready, "engine ready")
    error_message = "ready must be the line engine ready"
  }
  assert {
    condition     = strcontains(module.scale_alerts[0].filters.down, "Application shutdown complete.")
    error_message = "the down alert must watch the uvicorn shutdown line"
  }
  assert {
    condition     = module.model.runpod_env["SLACK_BOT_TOKEN"] == "{{ RUNPOD_SECRET_slack_bot_token }}" && module.model.runpod_env["SLACK_CHANNEL"] == "{{ RUNPOD_SECRET_slack_channel }}" && endswith(module.model.runpod_env["SLACK_TITLE"], " on Runpod")
    error_message = "the Runpod container needs the Slack token and channel from Runpod secrets, and a title"
  }
}
