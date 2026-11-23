# Slack messages for Runpod scale changes. Runpod writes no logs to GCP, so the Vertex AI way
# (log-based alerts on the model logs) does not work for them. Cloud Scheduler starts the job scale-watch every minute.
# It reads the up worker count of every Runpod endpoint of the account, and prints 1 line per
# change (scale_watch.py). The alerts.tf of each deployment sends these lines to the Slack channel models-slack.
# Cost: about 1440 short job runs per day (1 vCPU, a few seconds each), a few USD per month.

resource "google_storage_bucket" "scale_watch" {
  project                     = var.project_id
  name                        = "${var.project_id}-scale-watch"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true # only state.json: the last counts, made again by the next run

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "scale_watch" {
  project      = var.project_id
  account_id   = "scale-watch"
  display_name = "Cloud Run job scale-watch and its scheduler"

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "scale_watch" {
  bucket = google_storage_bucket.scale_watch.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.scale_watch.email}"

  lifecycle {
    replace_triggered_by = [google_storage_bucket.scale_watch]
  }
}

resource "google_secret_manager_secret_iam_member" "scale_watch" {
  for_each = {
    RUNPOD_API_KEY = google_secret_manager_secret.runpod_api_key.secret_id
  }

  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scale_watch.email}"
}

resource "google_cloud_run_v2_job" "scale_watch" {
  project             = var.project_id
  location            = var.region
  name                = "scale-watch"
  deletion_protection = false

  template {
    task_count = 1

    template {
      service_account = google_service_account.scale_watch.email
      timeout         = "120s"
      max_retries     = 0 # the next run comes 1 minute later

      containers {
        # Stock Python through the Docker Hub proxy repo (no build, no Docker Hub pull limit).
        image   = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.dockerhub.repository_id}/library/python:3.13.9-slim"
        command = ["python3"]
        args    = ["-u", "-c", file("${path.module}/scale_watch.py")]

        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }

        env {
          name  = "STATE_BUCKET"
          value = google_storage_bucket.scale_watch.name
        }

        # Static blocks: a dynamic block over the IAM members made the provider fail at apply ("inconsistent final plan").
        env {
          name = "RUNPOD_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.runpod_api_key.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_version.runpod_api_key, google_secret_manager_secret_iam_member.scale_watch]
}

resource "google_cloud_run_v2_job_iam_member" "scale_watch" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.scale_watch.name
  role     = "roles/run.invoker" # includes run.jobs.run
  member   = "serviceAccount:${google_service_account.scale_watch.email}"
}

resource "google_cloud_scheduler_job" "scale_watch" {
  project          = var.project_id
  region           = var.region
  name             = "scale-watch"
  schedule         = "* * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "60s"

  # No retry_config: the default is 0 retries, and the API returns no block for it (a block here drifts on every plan).

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.scale_watch.name}:run"

    oauth_token {
      service_account_email = google_service_account.scale_watch.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scale_watch]
}
