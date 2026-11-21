# Slack channel for the scale notifications. Deployments find it by display name (infra/modules/scale-alerts).
# Write-only: the token value is not in Terraform state. To rotate it, change SLACK_BOT_TOKEN in .env and raise auth_token_wo_version.
resource "google_monitoring_notification_channel" "slack" {
  project      = var.project_id
  type         = "slack"
  display_name = "models-slack"
  labels = {
    channel_name = var.slack_channel
  }

  sensitive_labels {
    auth_token_wo         = var.slack_bot_token
    auth_token_wo_version = 1
  }

  # Google adds the label "team" (the Slack workspace name). An update that removes it fails with HTTP 400, because
  # the write-only auth_token is not sent again.
  lifecycle {
    ignore_changes = [labels["team"]]
  }

  depends_on = [google_project_service.apis]
}
