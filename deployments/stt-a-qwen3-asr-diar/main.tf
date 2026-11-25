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
  # modal is first (the default for the old paths and the UI): on 2026-11-25 it was the only platform with a free GPU.
  platforms = ["modal", "vertex", "runpod"]
  # 3 weights-copy runs fill this folder: asr/, aligner/ and pyannote/ (see README.md). Vertex AI copies it from GCS
  # at start; on Runpod it is on the network volume (scripts/runpod-weights.py copies it there); on Modal it is on the
  # Modal Volume (scripts/platforms/modal.py fills it from Hugging Face).
  model_dir = "stt-a-qwen3-asr-diar"
  # Made by infra/core (main.tf). Large audio goes there through the STT API service (stt_api.tf).
  audio_bucket = "${var.project_id}-stt-audio"
  # Gateway ID and API ID. The API itself and the shared API key are in infra/core/gateways.tf (local.gateway_apis).
  gateway_id = "stt-a-qwen3-asr-diar"

  # The STT API service paths (stt_api.tf): their own backend, not the CORS proxy. Each also gets /<platform><path>.
  # transcribe waits for the GPU and scores reads every version, so they get 300 s; the other routes answer at once.
  files_paths = {
    "/v1beta/uploads"                                = ["post"]
    "/v1beta/files"                                  = ["get"]
    "/v1beta/files/{id}"                             = ["get"]
    "/v1beta/files/{id}/transcribe"                  = ["post"]
    "/v1beta/files/{id}/audio"                       = ["get"]
    "/v1beta/files/{id}/reference"                   = ["get", "put"]
    "/v1beta/files/{id}/versions/{version_id}"       = ["get"]
    "/v1beta/files/{id}/versions/{version_id}/names" = ["put"]
    "/v1beta/files/{id}/versions/{version_id}/score" = ["get"]
    "/v1beta/scores"                                 = ["get"]
  }
  long_paths = ["/v1beta/files/{id}/transcribe", "/v1beta/scores"]
}

module "model" {
  source = "../../infra/modules/model"

  project_id     = var.project_id
  region         = var.region
  gateway_region = var.gateway_region
  name           = "stt-a-qwen3-asr-diar" # base name on every platform (the current Vertex AI name: keeps the endpoint)
  gateway_id     = local.gateway_id
  platforms      = local.platforms

  spec = {
    # Own image, built by services/speech_engine/cloudbuild.yaml into the infra/core models repo.
    image = { own = "stt-a-qwen3-asr-diar:${var.image_tag}" }
    # No args: speech_engine/main.py reads PORT (or AIP_HTTP_PORT) and MODEL (or AIP_STORAGE_URI) itself.
    args = []
    env = {
      # The allow-list for audio URIs: gs:// (Vertex AI) and signed https://storage.googleapis.com/ URLs (any platform).
      AUDIO_BUCKET = local.audio_bucket
      # vLLM (Qwen3-ASR) shares the 24 GB GPU with the aligner and Pyannote. speech_engine/models.py reads these.
      GPU_MEMORY_UTILIZATION = "0.5"
      MAX_MODEL_LEN          = "16384"
      # The setup record of each answer (speech_engine/main.py SETUP): change it with the models or their settings, so
      # the evaluation can compare setups. The model names match the weights-copy HF_REPO values in README.md. The
      # adapter adds SETUP_PLATFORM; the answer adds the GPU name.
      SETUP_ASR         = "Qwen3-ASR-1.7B"
      SETUP_ALIGNER     = "Qwen3-ForcedAligner-0.6B"
      SETUP_DIARIZATION = "pyannote/speaker-diarization-community-1"
      SETUP_IMAGE_TAG   = var.image_tag
    }
    port         = 8080
    health_route = "/health"
    routes       = ["/v1beta/interactions"]
    gpu          = "L4"
    max_replicas = 1
    idle_seconds = 300
    # hf_repo is a label here: both platforms read the copy in gcs_dir (GCS on Vertex AI, the volume on Runpod).
    weights = { hf_repo = "Qwen/Qwen3-ASR-1.7B", gcs_dir = local.model_dir }
  }

  platform_options = {
    # Modal (infra/modules/platform-modal): scripts/deploy.py runs scripts/platforms/modal.py after apply. 4 cores and
    # 32 GiB are the default size (ffmpeg decode and Pyannote run on the CPU).
    modal = {
      workspace = var.modal_workspace
      command   = ["python3", "-m", "speech_engine.main"] # the image ENTRYPOINT (Modal does not run it)
      workdir   = "/srv"
      volume    = "stt-a-weights"
      # L4 first (the cheapest 24 GB GPU, $0.80/h), then A10 (a plain A10 or an A10G, $1.10/h) when no L4 is free
      # (user decision 2026-11-25). With L4 only, a cold start waited 3 to 15 min for an L4; A10 starts came in seconds.
      gpus = ["L4", "A10"]
      # Volume folder -> Hugging Face repo: the same HF_REPO values as the weights-copy runs in README.md.
      hf_repos = {
        asr      = "Qwen/Qwen3-ASR-1.7B"
        aligner  = "Qwen/Qwen3-ForcedAligner-0.6B"
        pyannote = "pyannote/speaker-diarization-community-1"
      }
      # The engine posts "ready" and "scaled to 0" itself (SLACK_BOT_TOKEN and SLACK_CHANNEL: a Modal secret from .env).
      env = { SLACK_TITLE = "STT-A Qwen3 ASR + speakers on Modal" }
    }
    vertex = {
      # 12 vCPU and 48 GB RAM: ffmpeg decode and Pyannote clustering run on the CPU.
      machine_type          = "g2-standard-12"
      shared_memory_size_mb = 16384
      deployment_timeout    = "1800s"
      predict_route         = "/v1beta/interactions" # :rawPredict. The app has 1 route.
    }
    runpod = {
      # 24 GB GPUs, as the L4. All of them run bf16.
      gpu_pools = ["AMPERE_24", "ADA_24"]
      env = {
        # Slack messages from the container itself (speech_engine/main.py: "ready" after the load, "scaled to 0" at SIGTERM). Runpod
        # writes no logs to GCP. The 2 values are Runpod secrets that scripts/hcp-sync.py makes from .env.
        SLACK_BOT_TOKEN = "{{ RUNPOD_SECRET_slack_bot_token }}"
        SLACK_CHANNEL   = "{{ RUNPOD_SECRET_slack_channel }}"
        SLACK_TITLE     = "STT-A Qwen3 ASR + speakers on Runpod"
      }
      # The weights: 1 volume per data center (all with the S3 API for scripts/runpod-weights.py). A worker starts only
      # where a volume is, and 24 GB GPUs are often out of stock in 1 data center, so 3 give more chances.
      # EU-RO-1 is excluded (the volume stays): on 2026-11-24 the load balancer never reached a worker there.
      volume = { data_centers = ["EU-RO-1", "EUR-IS-1", "EU-CZ-1"], size_gb = 20, excluded_data_centers = ["EU-RO-1"] }
      # Parked on 2026-11-24: the load balancer did not reach the worker in EU-CZ-1 either. No worker starts.
      workers_max = 0
      # FlashBoot off: the account allows 3 FlashBoot endpoints, and a replace of this endpoint needs a 4th slot.
      flashboot = "OFF"
    }
  }

  extra_paths = { for p, methods in local.files_paths : p => {
    backend_url = module.stt_api.url
    methods     = methods
    deadline    = contains(local.long_paths, p) ? 300 : 30
  } }
  # "transcribe" in the STT API service calls the GPU through the proxy.
  proxy_invokers = [module.stt_api.service_account_email]
}

# gs:// input (file_uri) on Vertex AI is read by the model SA. Read only. Runpod gets signed URLs.
resource "google_storage_bucket_iam_member" "model_audio" {
  bucket = local.audio_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${module.model.vertex_service_account_email}"
}
