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
  title           = "LLM-A Gemma 4 12B"
  resource_filter = "resource.type=\"aiplatform.googleapis.com/Endpoint\" AND resource.labels.endpoint_id=\"${module.model.vertex_endpoint_id}\""
  # vLLM loads the model before it starts uvicorn, so this line means ready.
  ready_text           = "Application startup complete."
  notification_channel = data.google_monitoring_notification_channel.slack.name
}

# Runpod writes no logs to GCP. The infra/core job scale-watch checks it every minute and prints
# "scale-watch: <platform> <id> ready" or "... scaled to 0". These alerts send those lines to Slack.
module "platform_alerts" {
  source   = "../../infra/modules/scale-alerts"
  for_each = module.model.scale_watch_ids

  project_id           = var.project_id
  title                = "LLM-A Gemma 4 12B on ${title(each.key)}"
  resource_filter      = "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"scale-watch\""
  ready_text           = "scale-watch: ${each.key} ${each.value} ready"
  down_text            = "scale-watch: ${each.key} ${each.value} scaled to 0"
  notification_channel = data.google_monitoring_notification_channel.slack.name
}
