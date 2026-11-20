variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "title" {
  description = "Model title in the Slack message, for example \"LLM-A Gemma 4 12B\"."
  type        = string
}

variable "resource_filter" {
  description = "Cloud Logging filter that selects the logs of this model only, for example resource.type and the service name or endpoint ID."
  type        = string

  validation {
    condition     = trimspace(var.resource_filter) != ""
    error_message = "resource_filter must not be empty: an empty filter matches the logs of every model."
  }
}

variable "ready_text" {
  description = "Log line text that means the model is ready (after the model loads)."
  type        = string

  validation {
    condition     = trimspace(var.ready_text) != "" && !strcontains(var.ready_text, "\"")
    error_message = "ready_text must not be empty and must not contain a double quote."
  }
}

variable "down_text" {
  description = "Log line text that means the container stopped (scale down)."
  type        = string
  default     = "Application shutdown complete."

  validation {
    condition     = trimspace(var.down_text) != "" && !strcontains(var.down_text, "\"")
    error_message = "down_text must not be empty and must not contain a double quote."
  }
}

variable "notification_channel" {
  description = "Notification channel resource name (projects/<p>/notificationChannels/<id>), from infra/core."
  type        = string
}
