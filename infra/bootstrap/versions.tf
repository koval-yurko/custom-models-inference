terraform {
  required_version = ">= 1.11"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.10"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  # The Billing Budget API needs a quota project when you use user credentials (ADC).
  user_project_override = true
  billing_project       = var.project_id
}
