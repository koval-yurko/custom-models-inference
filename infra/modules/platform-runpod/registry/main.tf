# The ID of a Runpod registry credential, found by name (infra/core runpod_registry.tf makes it).
# A child module, so tests replace its output with override_module: the mock provider cannot fill the nested
# list of the runpod_registries data source.
terraform {
  required_version = ">= 1.11"

  required_providers {
    runpod = {
      source  = "runpod/runpod"
      version = "~> 2.0"
    }
  }
}

variable "name" {
  description = "Name of the registry credential."
  type        = string
}

data "runpod_registries" "this" {}

output "id" {
  description = "Credential ID, or null when no credential has this name."
  value       = one([for r in data.runpod_registries.this.registries : r.id if r.name == var.name])
}
