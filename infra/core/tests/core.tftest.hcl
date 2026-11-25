mock_provider "google" {
  # runpod_registry.tf decodes the key (base64 of "{}").
  mock_resource "google_service_account_key" {
    defaults = { private_key = "e30=" }
  }
}
mock_provider "google-beta" {}
mock_provider "runpod" {}

variables {
  project_id           = "p"
  billing_account      = "000000-000000-000000"
  hf_token             = "test"
  runpod_api_key       = "test"
  modal_api_key        = "test"
  runpod_s3_access_key = "test"
  runpod_s3_secret_key = "test"
  slack_bot_token      = "test"
  slack_channel        = "#models"
}

run "enables_apis_needed_by_first_apply" {
  command = plan

  assert {
    condition     = contains(keys(google_project_service.apis), "cloudresourcemanager.googleapis.com")
    error_message = "data.google_project needs the Cloud Resource Manager API"
  }
  assert {
    condition     = contains(keys(google_project_service.apis), "serviceusage.googleapis.com")
    error_message = "google_project_service needs the Service Usage API"
  }
  assert {
    condition     = contains(keys(google_project_service.apis), "monitoring.googleapis.com")
    error_message = "the Slack notification channel and the scale alerts need the Monitoring API"
  }
  assert {
    condition     = contains(keys(google_project_service.apis), "iamcredentials.googleapis.com")
    error_message = "the STT-A upload service signs URLs with the IAM Credentials API (signBlob)"
  }
}

run "budget_uses_budget_amount" {
  command = plan

  variables {
    budget_amount = 35
  }

  assert {
    condition     = google_billing_budget.monthly.amount[0].specified_amount[0].units == "35"
    error_message = "budget amount must come from var.budget_amount"
  }
}

run "rejects_non_integer_budget" {
  command = plan

  variables {
    budget_amount = 20.5
  }

  expect_failures = [var.budget_amount]
}

run "weights_copy_job" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_job.weights_copy.template[0].template[0].volumes[0].gcs[0].bucket == "p-models"
    error_message = "job must mount the weights bucket"
  }
  assert {
    condition     = google_cloud_run_v2_job.weights_copy.template[0].template[0].volumes[0].gcs[0].read_only == false
    error_message = "job must write to the bucket"
  }
  assert {
    condition     = one([for e in google_cloud_run_v2_job.weights_copy.template[0].template[0].containers[0].env : e.value_source[0].secret_key_ref[0].secret if e.name == "HF_TOKEN"]) == "hf-token"
    error_message = "HF_TOKEN must come from the hf-token secret"
  }
  assert {
    condition     = google_storage_bucket_iam_member.weights_copy.role == "roles/storage.objectAdmin" && google_secret_manager_secret_iam_member.weights_copy.role == "roles/secretmanager.secretAccessor"
    error_message = "job SA needs objectAdmin on the bucket and secretAccessor on the token"
  }
}

run "vertex_ai_foundation" {
  command = plan

  assert {
    condition     = contains(keys(google_project_service.apis), "aiplatform.googleapis.com")
    error_message = "Vertex AI deployments need the Vertex AI API"
  }
  assert {
    condition     = contains(keys(google_project_service.apis), "cloudquotas.googleapis.com")
    error_message = "preflight.py and the quota steps in infra/README.md read the L4 quota through the Cloud Quotas API"
  }
  assert {
    condition     = google_artifact_registry_repository.dockerhub.remote_repository_config[0].docker_repository[0].public_repository == "DOCKER_HUB"
    error_message = "Vertex AI pulls only from Artifact Registry, so Docker Hub needs a proxy repo"
  }
}

run "ui_bucket_is_read_only_for_the_public" {
  command = plan

  assert {
    condition     = google_storage_bucket_iam_member.ui_public_read.role == "roles/storage.legacyObjectReader"
    error_message = "the public may only read UI files (no list, no write)"
  }
  assert {
    condition     = google_storage_bucket.models.public_access_prevention == "enforced"
    error_message = "the weights bucket must stay private"
  }
}

run "slack_channel_keeps_token_out_of_state" {
  command = plan

  assert {
    condition     = google_monitoring_notification_channel.slack.type == "slack" && google_monitoring_notification_channel.slack.display_name == "models-slack"
    error_message = "deployments find the Slack channel by the display name models-slack"
  }
  assert {
    condition     = google_monitoring_notification_channel.slack.labels.channel_name == "#models"
    error_message = "channel_name must come from slack_channel"
  }
  assert {
    condition     = google_monitoring_notification_channel.slack.sensitive_labels[0].auth_token == null
    error_message = "the token must go to the write-only auth_token_wo, not to auth_token (state)"
  }
}

run "rejects_channel_without_hash" {
  command = plan

  variables {
    slack_channel = "models"
  }

  expect_failures = [var.slack_channel]
}

run "stt_audio_bucket" {
  command = plan

  assert {
    condition     = google_storage_bucket.stt_audio.name == "p-stt-audio" && google_storage_bucket.stt_audio.location == var.region
    error_message = "the STT audio bucket must be <project_id>-stt-audio in the region"
  }
  assert {
    condition     = google_storage_bucket.stt_audio.uniform_bucket_level_access && google_storage_bucket.stt_audio.public_access_prevention == "enforced" && !google_storage_bucket.stt_audio.force_destroy
    error_message = "the STT audio bucket must be private, and a destroy must not delete the stored files"
  }
  assert {
    condition     = length(google_storage_bucket.stt_audio.lifecycle_rule) == 0
    error_message = "stored audio and transcript versions are kept forever (no lifecycle rule)"
  }
  assert {
    condition = (
      length(google_storage_bucket.stt_audio.cors) == 1
      && google_storage_bucket.stt_audio.cors[0].method == tolist(["PUT"])
      && google_storage_bucket.stt_audio.cors[0].origin == tolist(["*"])
      && contains(google_storage_bucket.stt_audio.cors[0].response_header, "Content-Type")
      && contains(google_storage_bucket.stt_audio.cors[0].response_header, "x-goog-content-length-range")
    )
    error_message = "the browser must be able to PUT to the signed upload URL"
  }
}

run "runpod_key_secret" {
  command = plan

  assert {
    condition     = google_secret_manager_secret.runpod_api_key.secret_id == "runpod-api-key"
    error_message = "the CORS proxies read the secret runpod-api-key"
  }
  assert {
    condition     = google_secret_manager_secret_version.runpod_api_key.secret_data_wo_version == "1"
    error_message = "the key is write-only (not in state)"
  }
}

run "modal_key_secret" {
  command = plan

  assert {
    condition     = google_secret_manager_secret.modal_api_key.secret_id == "modal-api-key" && google_secret_manager_secret_version.modal_api_key.secret_data_wo_version == "1"
    error_message = "the CORS proxies read the write-only secret modal-api-key"
  }
}

run "scale_watch" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_job.scale_watch.name == "scale-watch" && google_cloud_scheduler_job.scale_watch.schedule == "* * * * *"
    error_message = "Cloud Scheduler starts the job scale-watch every minute"
  }
  assert {
    condition     = strcontains(google_cloud_scheduler_job.scale_watch.http_target[0].uri, "/jobs/scale-watch:run")
    error_message = "the scheduler calls the Cloud Run run API of the job"
  }
  assert {
    condition     = toset([for e in google_cloud_run_v2_job.scale_watch.template[0].template[0].containers[0].env : e.name]) == toset(["STATE_BUCKET", "RUNPOD_API_KEY"])
    error_message = "the job gets the state bucket and the Runpod key (from Secret Manager)"
  }
  assert {
    condition     = strcontains(google_cloud_run_v2_job.scale_watch.template[0].template[0].containers[0].args[2], "scale-watch: ")
    error_message = "the job runs scale_watch.py"
  }
  assert {
    condition     = google_storage_bucket.scale_watch.name == "p-scale-watch"
    error_message = "the state lives in its own small bucket"
  }
  assert {
    condition     = toset([for k, m in google_secret_manager_secret_iam_member.scale_watch : m.secret_id]) == toset(["runpod-api-key"])
    error_message = "the job SA reads only the Runpod key"
  }
}

run "runpod_pull_reads_only_the_models_repo" {
  command = plan

  assert {
    condition     = google_artifact_registry_repository_iam_member.runpod_pull.role == "roles/artifactregistry.reader" && google_artifact_registry_repository_iam_member.runpod_pull.repository == "models"
    error_message = "the Runpod pull SA reads the repo models only (not the project)"
  }
  assert {
    condition     = runpod_registry.gcp_models.name == "gcp-models" && runpod_registry.gcp_models.username == "_json_key"
    error_message = "the platform-runpod adapter finds the credential by the name gcp-models"
  }
}

run "runpod_s3_secrets_for_cloud_build_only" {
  command = plan


  assert {
    condition     = toset(keys(google_secret_manager_secret.runpod_s3)) == toset(["runpod-s3-access-key", "runpod-s3-secret-key"])
    error_message = "2 secrets for the Runpod S3 API key"
  }
  assert {
    condition     = toset([for m in values(google_secret_manager_secret_iam_member.runpod_s3_cloud_build) : m.role]) == toset(["roles/secretmanager.secretAccessor"]) && length(google_secret_manager_secret_iam_member.runpod_s3_cloud_build) == 2
    error_message = "the Cloud Build service account may read the 2 secrets (the member is known only after apply)"
  }
}
