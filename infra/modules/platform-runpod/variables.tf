# tflint-ignore: terraform_unused_declarations
variable "project_id" {
  description = "GCP project ID. Unused here: every adapter has the same inputs."
  type        = string
}

# tflint-ignore: terraform_unused_declarations
variable "region" {
  description = "GCP region. Unused here: every adapter has the same inputs."
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
  description = "Runpod options: name, gpu_pools, excluded_types, scaling_value, disk_gb, extra_args, env, hf_token_secret. See infra/README.md, \"Module: platform-runpod\"."
  type        = any
  default     = {}
}
