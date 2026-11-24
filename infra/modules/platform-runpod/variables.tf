variable "project_id" {
  description = "GCP project ID. The URL of an own image (Artifact Registry repo models) uses it."
  type        = string
}

variable "region" {
  description = "GCP region of the Artifact Registry repo models (own images)."
  type        = string
}

variable "name" {
  description = "Base name of the model. options.name overrides it on Runpod."
  type        = string
}

variable "spec" {
  description = "The model spec. The model facade (infra/modules/model) owns its type."
  type        = any
}

variable "options" {
  description = "Runpod options: name, gpu_pools, excluded_types, scaling_value, disk_gb, extra_args, env, hf_token_secret, volume ({ data_centers, size_gb, type, excluded_data_centers }), registry, workers_max. See infra/README.md, \"Module: platform-runpod\"."
  type        = any
  default     = {}
}
