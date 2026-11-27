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
    # Runpod platform. It reads RUNPOD_API_KEY from the env (scripts/hcp-sync.py sets it in the HCP workspace).
    runpod = {
      source  = "runpod/runpod"
      version = "~> 2.0"
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
  # Platforms and their common settings come from deploy.yaml. See infra/README.md, "Module: model (platforms)".
  deploy    = yamldecode(file("${path.module}/deploy.yaml"))
  platforms = [for p in local.deploy.platforms : p.id]
  cfg       = { for p in local.deploy.platforms : p.id => p }
  # Filled by the weights-copy job (TARGET_DIR).
  model_dir = "gemma-4-12b-it-qat-w4a16"
}

module "model" {
  source = "../../infra/modules/model"

  project_id     = var.project_id
  region         = var.region
  gateway_region = var.gateway_region
  name           = "llm-a-gemma4-12b-vllm" # base name on every platform (Vertex AI name, Runpod template and endpoint)
  gateway_id     = "llm-a-gemma4"          # the API in infra/core/gateways.tf
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
    # revision: the Hugging Face commit. Runpod downloads exactly this one; Vertex AI reads the copy in gcs_dir.
    weights = { hf_repo = "google/gemma-4-12B-it-qat-w4a16-ct", revision = "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee", gcs_dir = local.model_dir }
  }

  platform_options = {
    vertex = {
      serve                 = try(local.cfg.vertex.serve, true)
      machine_type          = "g2-standard-12"
      shared_memory_size_mb = 16384
      deployment_timeout    = "1800s"
      # vLLM streams the weights from GCS. L4 (Ada) has FP8, so the KV cache uses it.
      extra_args    = ["--load-format=runai_streamer", "--kv-cache-dtype=fp8"]
      predict_route = "/v1/chat/completions" # :rawPredict. Without it the adapter uses :invoke for every route.
    }
    # L4, A5000 or 3090: Ampere has no native FP8, so no --kv-cache-dtype=fp8 here. vLLM downloads the weights at start.
    runpod = {
      # serve, workers_max, gpu_pools: see deploy.yaml.
      serve       = try(local.cfg.runpod.serve, true)
      gpu_pools   = try(local.cfg.runpod.gpu_pools, ["AMPERE_24"])
      workers_max = try(local.cfg.runpod.workers_max, 1)
    }
  }
}
