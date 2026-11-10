variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region of the endpoint and the model."
  type        = string
}

variable "name" {
  description = "Model and endpoint display name, 6-49 chars: lowercase letters, digits and hyphens. Also the base of the service account ID and the endpoint ID."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,47}[a-z0-9]$", var.name))
    error_message = "name must be 6-49 chars, start with a lowercase letter, use only lowercase letters, digits and hyphens, and not end with a hyphen."
  }
}

variable "image" {
  description = "Full container image URL in Artifact Registry. Vertex AI cannot pull from Docker Hub or ghcr.io directly."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]+-docker\\.pkg\\.dev/", var.image))
    error_message = "image must be in Artifact Registry (<region>-docker.pkg.dev/...). Use the infra/core dockerhub or ghcr proxy repo for stock images."
  }
}

variable "args" {
  description = "Container args. $(AIP_STORAGE_URI) and other $(VAR) references are expanded by Vertex AI."
  type        = list(string)
  default     = []
}

variable "env" {
  description = "Plain environment variables (no secrets). Vertex AI sets the AIP_ variables itself."
  type        = map(string)
  default     = {}

  validation {
    condition     = !anytrue([for k in keys(var.env) : startswith(k, "AIP_")])
    error_message = "env must not set AIP_ variables. Vertex AI sets them."
  }
}

variable "port" {
  description = "Container port. Vertex AI sets $AIP_HTTP_PORT to this value."
  type        = number
  default     = 8080
}

variable "health_route" {
  description = "HTTP health route. It must return 200 when the model is ready."
  type        = string
  default     = "/health"
}

variable "predict_route" {
  description = "The 1 route that :predict and :rawPredict forward to, for example /v1/chat/completions. Set it to null when invoke_routes is true."
  type        = string
  default     = null
}

variable "invoke_routes" {
  description = "true: upload with invokeRoutePrefix = \"/*\" (Preview). Every container route is reachable through :invoke, and :predict and :rawPredict are off."
  type        = bool
  default     = false
}

variable "machine_type" {
  description = "Vertex AI machine type."
  type        = string
  default     = "g2-standard-8"
}

variable "accelerator_type" {
  description = "Accelerator type, for example NVIDIA_L4. null for CPU only."
  type        = string
  default     = "NVIDIA_L4"
}

variable "accelerator_count" {
  description = "Accelerators per replica."
  type        = number
  default     = 1
}

variable "shared_memory_size_mb" {
  description = "Shared memory (/dev/shm) in MB. vLLM needs it, for example 16384. null for the Vertex AI default."
  type        = number
  default     = null
}

variable "deployment_timeout" {
  description = "Time for the container to start and pass the health check."
  type        = string
  default     = "1800s"
}

variable "max_replica_count" {
  description = "Max replicas. Min is always 0 (scale to zero, Preview). Quota is reserved for this value."
  type        = number
  default     = 1

  validation {
    condition     = var.max_replica_count >= 1
    error_message = "max_replica_count must be at least 1."
  }
}

variable "idle_scaledown_period" {
  description = "Time without traffic before the deployment scales to 0. Vertex AI allows 300s to 28800s; its default is 3600s."
  type        = string
  default     = "300s"

  validation {
    condition     = can(regex("^[0-9]+s$", var.idle_scaledown_period)) && try(tonumber(trimsuffix(var.idle_scaledown_period, "s")) >= 300 && tonumber(trimsuffix(var.idle_scaledown_period, "s")) <= 28800, false)
    error_message = "idle_scaledown_period must be \"<seconds>s\" between 300s and 28800s."
  }
}

variable "min_scaleup_period" {
  description = "Time after a scale up before Vertex AI checks for a scale down. 300s to 28800s; the Vertex AI default is 3600s."
  type        = string
  default     = "300s"

  validation {
    condition     = can(regex("^[0-9]+s$", var.min_scaleup_period)) && try(tonumber(trimsuffix(var.min_scaleup_period, "s")) >= 300 && tonumber(trimsuffix(var.min_scaleup_period, "s")) <= 28800, false)
    error_message = "min_scaleup_period must be \"<seconds>s\" between 300s and 28800s."
  }
}

variable "weights_bucket" {
  description = "Weights bucket (<project_id>-models). The service account gets roles/storage.objectViewer on it. null means no weights."
  type        = string
  default     = null
}

variable "weights_dir" {
  description = "Folder in weights_bucket, the TARGET_DIR of the weights-copy job. It becomes the model artifactUri, so the container gets AIP_STORAGE_URI."
  type        = string
  default     = null
}
