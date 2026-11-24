# Created by infra/core/notifications.tf. Apply core first.
data "google_monitoring_notification_channel" "slack" {
  project      = var.project_id
  display_name = "models-slack"
}

# Slack messages for scale up (ready) and scale down. See infra/README.md, section "Scale notifications (Slack)".
# The filter watches the Vertex AI endpoint, so the alerts exist only when vertex is in local.platforms.
module "scale_alerts" {
  source = "../../infra/modules/scale-alerts"
  count  = contains(local.platforms, "vertex") ? 1 : 0

  project_id      = var.project_id
  title           = "LLM-B Qwen3.5 9B"
  resource_filter = "resource.type=\"aiplatform.googleapis.com/Endpoint\" AND resource.labels.endpoint_id=\"${module.model.vertex_endpoint_id}\""
  # Printed by image/app.py after the engine loads (uvicorn starts before the model).
  ready_text           = "engine ready"
  notification_channel = data.google_monitoring_notification_channel.slack.name
}

# Runpod: no alert here. The container posts its own Slack messages (SLACK_* env in main.tf), so the
# infra/core job scale-watch is not used for this model.
