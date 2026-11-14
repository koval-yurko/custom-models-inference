terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.10"
    }
    # API Gateway resources are only in google-beta.
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 8.10"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

locals {
  # Filled by the weights-copy job (TARGET_DIR) from RedHatAI/Qwen3.5-9B-FP8-dynamic.
  model_dir = "qwen3.5-9b-fp8"
  # Own image, built by image/cloudbuild.yaml into the infra/core models repo.
  image = "${var.region}-docker.pkg.dev/${var.project_id}/models/llm-b-qwen35-9b-fastapi:${var.image_tag}"
}

module "model" {
  source = "../../infra/modules/vertex-model"

  project_id = var.project_id
  region     = var.region
  name       = "llm-b-qwen35-9b-fastapi"
  image      = local.image
  # No args: image/app.py reads AIP_STORAGE_URI and AIP_HTTP_PORT itself. These env values tune the engine.
  env = {
    HF_HUB_OFFLINE    = "1"
    SERVED_MODEL_NAME = "qwen3.5-9b"
    MAX_MODEL_LEN     = "16384"
  }

  health_route = "/health"
  # :invoke reaches every route of app.py (/generate, /extract): POST https://<endpoint_dns>/v1/<endpoint>/invoke/<route>.
  invoke_routes = true

  machine_type          = "g2-standard-8"
  accelerator_type      = "NVIDIA_L4"
  accelerator_count     = 1
  shared_memory_size_mb = 16384
  deployment_timeout    = "1800s"
  max_replica_count     = 1

  weights_bucket = "${var.project_id}-models"
  weights_dir    = local.model_dir
}
