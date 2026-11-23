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
  # See infra/README.md, "Module: model (platforms)".
  platforms = ["vertex", "runpod"]
  # Filled by the weights-copy job (TARGET_DIR) from RedHatAI/Qwen3.5-9B-FP8-dynamic. Vertex AI streams it from GCS;
  # on Runpod it is on the network volume (scripts/runpod-weights.py copies it there).
  model_dir = "qwen3.5-9b-fp8"
  # The app.py routes that the gateway lets through. /health stays private.
  routes = ["/generate", "/extract"]
}

module "model" {
  source = "../../infra/modules/model"

  project_id     = var.project_id
  region         = var.region
  gateway_region = var.gateway_region
  name           = "llm-b-qwen35-9b-fastapi" # base name on every platform (the current Vertex AI name: keeps the endpoint)
  gateway_id     = "llm-b-qwen35-fastapi"    # the API in infra/core/gateways.tf
  platforms      = local.platforms

  spec = {
    # Own image, built by image/cloudbuild.yaml into the infra/core models repo.
    image = { own = "llm-b-qwen35-9b-fastapi:${var.image_tag}" }
    # No args: image/app.py reads PORT (or AIP_HTTP_PORT) and MODEL (or AIP_STORAGE_URI) itself. These env values tune the engine.
    args = []
    env = {
      SERVED_MODEL_NAME = "qwen3.5-9b"
      MAX_MODEL_LEN     = "16384"
    }
    port         = 8080
    health_route = "/health"
    routes       = local.routes
    gpu          = "L4"
    max_replicas = 1
    idle_seconds = 300
    # hf_repo is a label here: both platforms read the copy in gcs_dir (GCS on Vertex AI, the volume on Runpod).
    weights = { hf_repo = "RedHatAI/Qwen3.5-9B-FP8-dynamic", gcs_dir = local.model_dir }
  }

  platform_options = {
    vertex = {
      machine_type          = "g2-standard-8"
      shared_memory_size_mb = 16384
      deployment_timeout    = "1800s"
      # No predict_route: :invoke reaches every route of app.py (<endpoint>/invoke/<route>).
    }
    runpod = {
      # 24 GB GPUs, as the L4. Ampere (A5000, 3090) has no native FP8: vLLM runs the FP8 weights as W8A16, and the KV
      # cache stays in the model dtype.
      gpu_pools = ["AMPERE_24", "ADA_24"]
      env       = { KV_CACHE_DTYPE = "auto" }
      # The weights (about 14 GB): 1 volume per data center (all with the S3 API for scripts/runpod-weights.py). A worker
      # starts only where a volume is, and 24 GB GPUs are often out of stock in 1 data center, so 3 give more chances.
      # 40 GB: the S3 upload of model.safetensors (13.5 GB) keeps its parts on the volume until the complete call joins
      # them, so the copy needs about 2 times the largest file. A full volume answers 403.
      volume = { data_centers = ["EU-RO-1", "EUR-IS-1", "EU-CZ-1"], size_gb = 40 }
    }
  }
}
