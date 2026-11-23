locals {
  apis = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "compute.googleapis.com",
    "billingbudgets.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    # API Gateway with API keys (gateways.tf)
    "apigateway.googleapis.com",
    "servicemanagement.googleapis.com",
    "servicecontrol.googleapis.com",
    "apikeys.googleapis.com",
    # Vertex AI endpoints (infra/modules/platform-vertex)
    "aiplatform.googleapis.com",
    # Read GPU quotas (scripts/preflight.py --l4, gcloud beta quotas)
    "cloudquotas.googleapis.com",
    # Slack notification channel and the scale alerts of the deployments.
    "monitoring.googleapis.com",
    # signBlob for the signed upload URLs of STT-A (deployments/stt-a-qwen3-asr-diar/services/stt_api)
    "iamcredentials.googleapis.com",
    # Cloud Scheduler starts the scale-watch job every minute (scale_watch.tf)
    "cloudscheduler.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

data "google_project" "this" {
  project_id = var.project_id

  # Read at apply time, after the Cloud Resource Manager API is on.
  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket" "models" {
  project                     = var.project_id
  name                        = "${var.project_id}-models"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  depends_on = [google_project_service.apis]
}

# STT-A audio files and transcript versions (files/<id>/...). The STT API service gives signed PUT URLs.
resource "google_storage_bucket" "stt_audio" {
  project                     = var.project_id
  name                        = "${var.project_id}-stt-audio"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  # Stored audio and transcript versions are kept forever (STT-A history). A destroy must not delete them.
  force_destroy = false

  # The browser sends the file straight to the signed URL.
  cors {
    origin          = ["*"]
    method          = ["PUT"]
    response_header = ["Content-Type", "x-goog-content-length-range"]
    max_age_seconds = 600
  }

  depends_on = [google_project_service.apis]
}

resource "google_artifact_registry_repository" "models" {
  project       = var.project_id
  location      = var.region
  repository_id = "models"
  format        = "DOCKER"
  description   = "Custom model images."

  depends_on = [google_project_service.apis]
}

# Cloud Run cannot pull from ghcr.io directly; this remote repo proxies it.
resource "google_artifact_registry_repository" "ghcr" {
  project       = var.project_id
  location      = var.region
  repository_id = "ghcr"
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"
  description   = "Proxy for ghcr.io."

  remote_repository_config {
    description = "GitHub Container Registry"

    docker_repository {
      custom_repository {
        uri = "https://ghcr.io"
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# Vertex AI pulls images only from Artifact Registry; this remote repo proxies Docker Hub.
resource "google_artifact_registry_repository" "dockerhub" {
  project       = var.project_id
  location      = var.region
  repository_id = "dockerhub"
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"
  description   = "Proxy for Docker Hub."

  remote_repository_config {
    description = "Docker Hub"

    docker_repository {
      public_repository = "DOCKER_HUB"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account
  display_name    = "${var.project_id} monthly"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      # No currency_code: the API then uses the billing account currency.
      units = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }

  depends_on = [google_project_service.apis]
}
