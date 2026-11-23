variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region of the service (the same as the Vertex AI endpoint)."
  type        = string
}

variable "name" {
  description = "Cloud Run service name, for example \"<gateway_id>-proxy\"."
  type        = string
}

variable "targets" {
  description = "Platform id -> {url, append_path, auth}. The first path segment of a request picks the target (/vertex/v1/x). append_path = true: the proxy appends the rest of the path to url (Vertex AI :invoke base, Runpod), so the gateway must use APPEND_PATH_TO_ADDRESS. false: url is one fixed URL (Vertex AI :rawPredict). auth: google (the proxy SA token), runpod (an API key from secret_env)."
  type = map(object({
    url         = string
    append_path = bool
    auth        = string
  }))

  validation {
    condition     = alltrue([for t in values(var.targets) : startswith(t.url, "https://")])
    error_message = "Every target url must be an https URL."
  }
  validation {
    condition     = alltrue([for t in values(var.targets) : contains(["google", "runpod"], t.auth)])
    error_message = "Every target auth must be google or runpod."
  }
}

variable "default_platform" {
  description = "Platform id for a path without a platform prefix (the old paths)."
  type        = string

  validation {
    condition     = contains(keys(var.targets), var.default_platform)
    error_message = "default_platform must be a key of targets."
  }
}

variable "secret_env" {
  description = "Provider API keys: env var name (RUNPOD_API_KEY) -> Secret Manager secret ID."
  type        = map(string)
  default     = {}
}

variable "timeout" {
  description = "Request timeout of the proxy, for example \"300s\". Use the largest gateway deadline of the targets."
  type        = string
  default     = "300s"
}

variable "gateway_service_account_email" {
  description = "Service account of the API Gateway. It gets roles/run.invoker on the proxy. Only this one can call it."
  type        = string
}

variable "image" {
  description = "Stock image that runs cors_proxy.py (standard library only). Use the dockerhub proxy repo of infra/core."
  type        = string
}
