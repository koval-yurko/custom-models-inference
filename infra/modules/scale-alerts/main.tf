locals {
  events = {
    ready = { text = var.ready_text, subject = "🟢 ${var.title} is ready" }
    down  = { text = var.down_text, subject = "⚪ ${var.title} scaled to 0" }
  }
  # The line can be in textPayload (plain stdout) or in jsonPayload.message (structured log agents).
  filters = { for k, e in local.events : k => "${var.resource_filter} AND (textPayload:\"${e.text}\" OR jsonPayload.message:\"${e.text}\")" }
}

# Log-based alerts count container starts and stops, not 0 -> 1: a scale from 1 to 2 also sends "ready".
resource "google_monitoring_alert_policy" "this" {
  for_each = local.events

  project               = var.project_id
  display_name          = "${var.title}: ${each.key}"
  combiner              = "OR"
  notification_channels = [var.notification_channel]

  conditions {
    display_name = each.value.subject
    condition_matched_log {
      filter = local.filters[each.key]
    }
  }

  alert_strategy {
    auto_close           = "1800s"
    notification_prompts = ["OPENED"]
    notification_rate_limit {
      period = "300s"
    }
  }

  documentation {
    subject   = each.value.subject
    content   = each.value.subject
    mime_type = "text/markdown"
  }
}
