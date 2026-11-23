variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region of the Vertex AI endpoint and the CORS proxy."
  type        = string
}

variable "gateway_region" {
  description = "API Gateway region. It can differ from region."
  type        = string
}

variable "name" {
  description = "Base name of the model on every platform. platform_options.<id>.name overrides it for one platform."
  type        = string
}

variable "gateway_id" {
  description = "Gateway ID and API ID (the API in infra/core/gateways.tf). The proxy is \"<gateway_id>-proxy\"."
  type        = string
}

variable "platforms" {
  description = "Platform ids, in order. The first one is the default for the old paths without a prefix."
  type        = list(string)

  validation {
    condition     = length(var.platforms) > 0
    error_message = "platforms must not be empty."
  }
  validation {
    condition     = length(distinct(var.platforms)) == length(var.platforms)
    error_message = "platforms must not contain an id twice."
  }
  validation {
    # Phase 1: only the vertex adapter exists. Phase 3 adds runpod.
    condition     = alltrue([for p in var.platforms : contains(["vertex"], p)])
    error_message = "Supported platform ids: vertex."
  }
}

variable "spec" {
  description = "Platform-neutral model spec. See infra/README.md, \"Module: model (platforms)\"."
  type = object({
    image        = object({ stock = optional(string), own = optional(string) }) # exactly one is set
    args         = list(string)                                                 # may contain {model}
    env          = optional(map(string), {})
    port         = optional(number, 8080)
    health_route = string
    routes       = list(string) # gateway paths, each starts with /
    gpu          = optional(string)
    max_replicas = optional(number, 1)
    idle_seconds = optional(number, 300) # Vertex AI accepts 300 s or more
    weights = optional(object({
      hf_repo  = string
      revision = optional(string) # required for non-vertex platforms (phase 3)
      gcs_dir  = optional(string) # vertex: folder in gs://<project_id>-models
    }))
  })

  validation {
    condition     = (var.spec.image.stock == null) != (var.spec.image.own == null)
    error_message = "spec.image must set exactly one of stock and own."
  }
}

variable "platform_options" {
  description = "Options per platform id. The shapes differ per platform, so the type is any."
  type        = any
  default     = {}
}
