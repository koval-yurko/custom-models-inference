# Created by infra/core/notifications.tf. Apply core first.
data "google_monitoring_notification_channel" "slack" {
  project      = var.project_id
  display_name = "models-slack"
}

# Slack messages for scale up (ready) and scale down. See infra/README.md, section "Scale notifications (Slack)".
module "scale_alerts" {
  source = "../../infra/modules/scale-alerts"

  project_id      = var.project_id
  title           = "TTS-A Kokoro"
  resource_filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${module.service.service_name}\""
  # Cloud Run system log: the startup probe passed (uvicorn logs "startup complete" before that).
  ready_text           = "STARTUP HTTP probe succeeded"
  notification_channel = data.google_monitoring_notification_channel.slack.name
}
