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

variable "target" {
  description = "Vertex AI URL that the proxy calls: the :rawPredict URL (https://<endpoint_dns>/v1/projects/.../endpoints/<id>:rawPredict), or the :invoke base that ends in /invoke. For /invoke the proxy appends the request path, so the gateway must use path_translation APPEND_PATH_TO_ADDRESS."
  type        = string

  validation {
    condition     = startswith(var.target, "https://")
    error_message = "target must be an https URL."
  }
}

variable "gateway_service_account_email" {
  description = "Service account of the API Gateway. It gets roles/run.invoker on the proxy. Only this one can call it."
  type        = string
}

variable "image" {
  description = "Stock image that runs cors_proxy.py (standard library only). Use the dockerhub proxy repo of infra/core."
  type        = string
}
