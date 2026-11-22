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
  # 3 weights-copy runs fill this folder: asr/, aligner/ and pyannote/ (see README.md). speech_engine/models.py copies it to /models.
  model_dir = "stt-a-qwen3-asr-diar"
  # Own image, built by image/cloudbuild.yaml into the infra/core models repo.
  image = "${var.region}-docker.pkg.dev/${var.project_id}/models/stt-a-qwen3-asr-diar:${var.image_tag}"
  # Made by infra/core (main.tf). Large audio goes there through the STT API service (stt_api.tf).
  audio_bucket = "${var.project_id}-stt-audio"
}

module "model" {
  source = "../../infra/modules/vertex-model"

  project_id = var.project_id
  region     = var.region
  name       = "stt-a-qwen3-asr-diar"
  image      = local.image
  # No args: speech_engine/main.py reads AIP_STORAGE_URI and AIP_HTTP_PORT itself.
  env = {
    HF_HUB_OFFLINE = "1"
    AUDIO_BUCKET   = local.audio_bucket
    # vLLM (Qwen3-ASR) shares the L4 with the aligner and Pyannote. speech_engine/models.py reads these.
    GPU_MEMORY_UTILIZATION = "0.5"
    MAX_MODEL_LEN          = "16384"
    # The setup record of each answer (speech_engine/main.py SETUP): change it with the models or their settings, so the
    # evaluation can compare setups. The model names match the weights-copy HF_REPO values in README.md.
    SETUP_ASR         = "Qwen3-ASR-1.7B"
    SETUP_ALIGNER     = "Qwen3-ForcedAligner-0.6B"
    SETUP_DIARIZATION = "pyannote/speaker-diarization-community-1"
    SETUP_IMAGE_TAG   = var.image_tag
  }

  health_route  = "/health"
  predict_route = "/v1beta/interactions" # :rawPredict. The app has 1 route.

  # 12 vCPU and 48 GB RAM: ffmpeg decode and Pyannote clustering run on the CPU.
  machine_type          = "g2-standard-12"
  accelerator_type      = "NVIDIA_L4"
  accelerator_count     = 1
  shared_memory_size_mb = 16384
  deployment_timeout    = "1800s"
  max_replica_count     = 1

  weights_bucket = "${var.project_id}-models"
  weights_dir    = local.model_dir
}

# gs:// input (file_uri) is read by the model SA. Read only.
resource "google_storage_bucket_iam_member" "model_audio" {
  bucket = local.audio_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${module.model.service_account_email}"
}
