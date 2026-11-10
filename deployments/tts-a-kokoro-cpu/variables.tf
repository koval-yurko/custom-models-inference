variable "project_id" {
  description = "GCP project ID (the infra/core project)."
  type        = string
}

variable "region" {
  description = "Region. Must match the infra/core region."
  type        = string
  default     = "europe-west4"
}

variable "invoker_email" {
  description = "Google account that may call the service."
  type        = string
}

variable "gateway_region" {
  description = "API Gateway region. API Gateway is not in every region; it can differ from var.region."
  type        = string
  default     = "europe-west1"
}
