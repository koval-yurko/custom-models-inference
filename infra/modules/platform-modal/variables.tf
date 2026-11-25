variable "project_id" {
  description = "GCP project ID. The URL of the own image (Artifact Registry repo models) uses it."
  type        = string
}

variable "region" {
  description = "GCP region of the Artifact Registry repo models."
  type        = string
}

variable "name" {
  description = "Base name of the model. options.name overrides it on Modal. It is the Modal app name and the web label."
  type        = string
}

variable "spec" {
  description = "The model spec. The model facade (infra/modules/model) owns its type."
  type        = any
}

variable "options" {
  description = "Modal options: workspace (required), command (required), workdir, name, gpus, cpu, memory_mb, timeout, volume, hf_repos, env. See infra/README.md, \"Module: platform-modal\"."
  type        = any
}
