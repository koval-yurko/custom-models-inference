variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region of the Vertex AI endpoint."
  type        = string
}

variable "name" {
  description = "Base name of the model. options.name overrides it on Vertex AI."
  type        = string
}

variable "spec" {
  description = "The model spec. The model facade (infra/modules/model) owns its type."
  type        = any
}

variable "options" {
  description = "Vertex AI options: name, machine_type, shared_memory_size_mb, deployment_timeout, extra_args, env, predict_route. See infra/README.md, \"Module: platform-vertex\"."
  type        = any
  default     = {}
}
