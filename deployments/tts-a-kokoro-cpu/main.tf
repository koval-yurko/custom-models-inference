terraform {
  required_version = ">= 1.7"

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
}

module "service" {
  source = "../../infra/modules/model-service"

  project_id = var.project_id
  region     = var.region
  name       = "tts-a-kokoro-cpu"
  # Pulled through the bootstrap "ghcr" remote repo; ghcr.io/remsky/kokoro-fastapi-cpu has the model inside.
  image              = "${var.region}-docker.pkg.dev/${var.project_id}/ghcr/remsky/kokoro-fastapi-cpu:v0.10.0"
  cpu                = "4"
  memory             = "8Gi"
  startup_probe_path = "/health"
  invokers           = ["user:${var.invoker_email}"]
}
