# Created by infra/core/notifications.tf. Apply core first.
data "google_monitoring_notification_channel" "slack" {
  project      = var.project_id
  display_name = "models-slack"
}

# Slack messages for scale up (ready) and scale down. See infra/README.md, section "Scale notifications (Slack)".
module "scale_alerts" {
  source = "../../infra/modules/scale-alerts"

  project_id      = var.project_id
  title           = "LLM-A Gemma 4 12B"
  resource_filter = "resource.type=\"aiplatform.googleapis.com/Endpoint\" AND resource.labels.endpoint_id=\"${module.model.endpoint_id}\""
  # vLLM loads the model before it starts uvicorn, so this line means ready.
  ready_text           = "Application startup complete."
  notification_channel = data.google_monitoring_notification_channel.slack.name
}
