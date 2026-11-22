# Created by infra/core/notifications.tf. Apply core first.
data "google_monitoring_notification_channel" "slack" {
  project      = var.project_id
  display_name = "models-slack"
}

# Slack messages for scale up (ready) and scale down. See infra/README.md, section "Scale notifications (Slack)".
module "scale_alerts" {
  source = "../../infra/modules/scale-alerts"

  project_id      = var.project_id
  title           = "STT-A Qwen3 ASR + speakers"
  resource_filter = "resource.type=\"aiplatform.googleapis.com/Endpoint\" AND resource.labels.endpoint_id=\"${module.model.endpoint_id}\""
  # Printed by speech_engine/main.py after the 3 models load (uvicorn starts before the models).
  ready_text           = "models ready"
  notification_channel = data.google_monitoring_notification_channel.slack.name
}
