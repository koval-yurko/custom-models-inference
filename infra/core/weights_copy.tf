# One shared Cloud Run job copies a Hugging Face repo into the weights bucket.
# Set the repo and the target folder per execution:
#   gcloud run jobs execute weights-copy --region <region> --wait \
#     --update-env-vars HF_REPO=<org/repo>,TARGET_DIR=<folder>

resource "google_secret_manager_secret" "hf_token" {
  project   = var.project_id
  secret_id = "hf-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# Write-only: the token value is not in Terraform state. To rotate it, change HF_TOKEN in .env and raise secret_data_wo_version.
resource "google_secret_manager_secret_version" "hf_token" {
  secret                 = google_secret_manager_secret.hf_token.id
  secret_data_wo         = var.hf_token
  secret_data_wo_version = 1
}

resource "google_service_account" "weights_copy" {
  project      = var.project_id
  account_id   = "weights-copy"
  display_name = "Cloud Run job weights-copy"

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "weights_copy" {
  bucket = google_storage_bucket.models.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.weights_copy.email}"
}

resource "google_secret_manager_secret_iam_member" "weights_copy" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.hf_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.weights_copy.email}"
}

resource "google_cloud_run_v2_job" "weights_copy" {
  project             = var.project_id
  location            = var.region
  name                = "weights-copy"
  deletion_protection = false

  template {
    task_count = 1

    template {
      service_account = google_service_account.weights_copy.email
      timeout         = "3600s"
      max_retries     = 1

      containers {
        image   = "python:3.12-slim"
        command = ["sh", "-c"]
        args = [<<-EOT
          set -eu
          : "$${HF_REPO:?set HF_REPO with --update-env-vars}" "$${TARGET_DIR:?set TARGET_DIR with --update-env-vars}"
          pip install -q --no-cache-dir 'huggingface_hub>=1,<2'
          hf download "$HF_REPO" --local-dir "/models/$TARGET_DIR"
          ls -la "/models/$TARGET_DIR"
        EOT
        ]

        env {
          name = "HF_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.hf_token.secret_id
              version = "latest"
            }
          }
        }
        # The container disk is in memory; no Xet chunk cache, so a 10 GB file does not fill RAM twice.
        env {
          name  = "HF_XET_CHUNK_CACHE_SIZE_BYTES"
          value = "0"
        }

        resources {
          limits = {
            cpu    = "4"
            memory = "16Gi"
          }
        }

        volume_mounts {
          name       = "weights"
          mount_path = "/models"
        }
      }

      volumes {
        name = "weights"
        gcs {
          bucket    = google_storage_bucket.models.name
          read_only = false
        }
      }
    }
  }

  depends_on = [
    google_storage_bucket_iam_member.weights_copy,
    google_secret_manager_secret_iam_member.weights_copy,
  ]
}
