terraform {
  required_version = ">= 1.11"

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
  # Platforms of this model, in order. The first one is the default for the old paths without a prefix.
  # See infra/README.md, "Module: model (platforms)".
  platforms = ["vertex"]
  # Filled by the weights-copy job (TARGET_DIR).
  model_dir = "gemma-4-12b-it-qat-w4a16"
}

module "model" {
  source = "../../infra/modules/model"

  project_id     = var.project_id
  region         = var.region
  gateway_region = var.gateway_region
  name           = "llm-a-gemma4-12b"    # base name on every platform
  gateway_id     = "llm-a-gemma4-vertex" # the API in infra/core/gateways.tf
  platforms      = local.platforms

  spec = {
    # Stock image, flags only. On Vertex AI it comes through the infra/core Docker Hub proxy.
    image = { stock = "vllm/vllm-openai:v0.33.0" }
    # Flags that work on every platform and GPU. {model} becomes the weights path of the platform.
    args = [
      "--model={model}",
      "--served-model-name=gemma-4-12b",
      "--max-model-len=32768",
      "--host=0.0.0.0",
      "--port=8080",
    ]
    port         = 8080
    health_route = "/health"
    routes       = ["/v1/chat/completions"]
    gpu          = "L4"
    max_replicas = 1
    idle_seconds = 300
    weights      = { hf_repo = "google/gemma-4-12B-it-qat-w4a16-ct", gcs_dir = local.model_dir }
  }

  platform_options = {
    vertex = {
      name                  = "llm-a-gemma4-12b-vllm-vertex" # the current Vertex AI name: keeps the endpoint ID
      machine_type          = "g2-standard-12"
      shared_memory_size_mb = 16384
      deployment_timeout    = "1800s"
      # vLLM streams the weights from GCS. L4 (Ada) has FP8, so the KV cache uses it.
      extra_args    = ["--load-format=runai_streamer", "--kv-cache-dtype=fp8"]
      predict_route = "/v1/chat/completions" # :rawPredict. Without it the adapter uses :invoke for every route.
    }
  }
}
