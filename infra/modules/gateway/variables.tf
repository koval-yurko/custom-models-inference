variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Gateway region. API Gateway is not in every region; it can differ from the model region."
  type        = string
}

variable "gateway_id" {
  description = "Gateway ID and API ID. The API itself and the shared API key are in infra/core/gateways.tf (local.gateway_apis)."
  type        = string

  validation {
    # The gateway SA ID is "<gateway_id>-gw" (max 30).
    condition     = length(var.gateway_id) <= 27
    error_message = "gateway_id must be 27 chars or less."
  }
}

variable "backend_url" {
  description = "URL of the CORS proxy. Every model route goes there."
  type        = string

  validation {
    condition     = startswith(var.backend_url, "https://")
    error_message = "backend_url must be an https URL."
  }
}

variable "platforms" {
  description = "Platform ids in order. The first one is the default: the old paths without a prefix use its deadline."
  type        = list(string)
}

variable "routes" {
  description = "Model routes, for example [\"/v1/chat/completions\"]. Each gets the old path and one /<platform><route> path."
  type        = list(string)

  validation {
    condition     = alltrue([for r in var.routes : startswith(r, "/")])
    error_message = "Every route must start with /."
  }
}

variable "methods" {
  description = "HTTP methods of the model routes (lowercase)."
  type        = list(string)
  default     = ["post"]
}

variable "deadlines" {
  description = "Gateway backend deadline in seconds, per platform id."
  type        = map(number)
}

variable "extra_paths" {
  description = "Paths to another backend (for example the STT-A stt_api service): path -> {backend_url, methods, deadline}. They get the same prefix rule as the routes."
  type = map(object({
    backend_url = string
    methods     = list(string)
    deadline    = number
  }))
  default = {}
}
