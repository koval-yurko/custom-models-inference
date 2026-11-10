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

locals {
  # Folder in the weights bucket, filled by the infra/core weights-copy job from google/gemma-4-12B-it-qat-w4a16-ct.
  model_dir = "gemma-4-12b-it-qat-w4a16"
}

module "service" {
  source = "../../infra/modules/model-service"

  project_id = var.project_id
  region     = var.region
  name       = "llm-a-gemma4-12b-vllm"
  # Stock image, flags only. Pinned: Gemma 4 QAT needs a recent vLLM.
  image = "docker.io/vllm/vllm-openai:v0.33.0"
  args = [
    "--model", "/models/${local.model_dir}",
    "--served-model-name", "gemma-4-12b",
    "--max-model-len", "32768",
    "--kv-cache-dtype", "fp8",
    "--host", "0.0.0.0",
    "--port", "8080",
  ]
  # Weights are in the bucket; never call Hugging Face at start.
  env = { HF_HUB_OFFLINE = "1" }

  gpu_type       = "nvidia-l4"
  cpu            = "8"
  memory         = "32Gi"
  concurrency    = 16
  max_instances  = 1
  timeout        = "600s"
  weights_bucket = "${var.project_id}-models"

  startup_probe_path = "/health"
  # 10 GB over GCS FUSE plus engine start: allow 20 min.
  startup_failure_threshold = 120

  invokers = ["user:${var.invoker_email}"]
}
