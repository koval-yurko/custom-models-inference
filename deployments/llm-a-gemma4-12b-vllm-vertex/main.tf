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
  # Same folder as the Cloud Run version (deployments/llm-a-gemma4-12b-vllm), filled by the weights-copy job.
  model_dir = "gemma-4-12b-it-qat-w4a16"
}

module "model" {
  source = "../../infra/modules/vertex-model"

  project_id = var.project_id
  region     = var.region
  name       = "llm-a-gemma4-12b-vllm-vertex"
  # Stock image through the infra/core Docker Hub proxy, flags only. Same pin as the Cloud Run version.
  image = "${var.region}-docker.pkg.dev/${var.project_id}/dockerhub/vllm/vllm-openai:v0.33.0"
  args = [
    # Vertex AI sets AIP_STORAGE_URI from the model artifactUri; vLLM streams the weights from GCS.
    "--model=$(AIP_STORAGE_URI)",
    "--load-format=runai_streamer",
    "--served-model-name=gemma-4-12b",
    "--max-model-len=32768",
    "--kv-cache-dtype=fp8",
    "--host=0.0.0.0",
    "--port=8080",
  ]
  env = { HF_HUB_OFFLINE = "1" }

  health_route  = "/health"
  predict_route = "/v1/chat/completions" # :rawPredict. For the full OpenAI API, use invoke_routes = true instead.

  machine_type          = "g2-standard-8"
  accelerator_type      = "NVIDIA_L4"
  accelerator_count     = 1
  shared_memory_size_mb = 16384
  deployment_timeout    = "1800s"
  max_replica_count     = 1

  weights_bucket = "${var.project_id}-models"
  weights_dir    = local.model_dir
}
