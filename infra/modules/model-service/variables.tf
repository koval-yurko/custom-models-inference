variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region of the Cloud Run service."
  type        = string
}

variable "name" {
  description = "Cloud Run service name, 6-49 chars: lowercase letters, digits and hyphens. Also the base of the service account ID."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,47}[a-z0-9]$", var.name))
    error_message = "name must be 6-49 chars, start with a lowercase letter, use only lowercase letters, digits and hyphens, and not end with a hyphen."
  }
}

variable "image" {
  description = "Full container image URL."
  type        = string
}

variable "args" {
  description = "Container args."
  type        = list(string)
  default     = []
}

variable "env" {
  description = "Plain environment variables (no secrets)."
  type        = map(string)
  default     = {}
}

variable "port" {
  description = "Container port. Cloud Run sets $PORT to this value."
  type        = number
  default     = 8080
}

variable "cpu" {
  description = "CPU limit."
  type        = string
  default     = "4"
}

variable "memory" {
  description = "Memory limit."
  type        = string
  default     = "16Gi"
}

variable "gpu_type" {
  description = "null for CPU only, or \"nvidia-l4\" (needs at least 4 CPU and 16Gi) or \"nvidia-rtx-pro-6000\" (needs at least 20 CPU and 80Gi)."
  type        = string
  default     = null
}

variable "concurrency" {
  description = "Max concurrent requests per instance."
  type        = number
  default     = 4
}

variable "max_instances" {
  description = "Max instances. Min is always 0."
  type        = number
  default     = 1
}

variable "timeout" {
  description = "Request timeout."
  type        = string
  default     = "300s"
}

variable "startup_probe_path" {
  description = "HTTP path for the startup probe. null means a TCP probe on port."
  type        = string
  default     = null
}

variable "startup_failure_threshold" {
  description = "Startup probe failures allowed, with a 10 s period."
  type        = number
  default     = 60
}

variable "weights_bucket" {
  description = "GCS bucket to mount read-only at /models. null means no volume."
  type        = string
  default     = null
}

variable "invokers" {
  description = "IAM members allowed to call the service, for example [\"user:me@example.com\"]."
  type        = list(string)

  validation {
    condition     = !anytrue([for m in var.invokers : contains(["allUsers", "allAuthenticatedUsers"], m)])
    error_message = "Services are private: invokers must not contain allUsers or allAuthenticatedUsers."
  }
}
