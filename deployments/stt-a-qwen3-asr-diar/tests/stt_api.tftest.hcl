mock_provider "google" {
  # The gateway module needs an https backend URL.
  mock_resource "google_cloud_run_v2_service" {
    defaults = { uri = "https://svc" }
  }
}
mock_provider "google-beta" {}
mock_provider "runpod" {
  mock_resource "runpod_serverless_endpoint" {
    defaults = { request_urls = { base = "https://ep1.api.runpod.ai" } }
  }
  mock_resource "runpod_network_volume" {
    defaults = { id = "vol1" }
  }
}

# The registry credential of infra/core, found by name. The mock provider cannot fill the data source.
override_module {
  target  = module.model.module.runpod[0].module.registry[0]
  outputs = { id = "reg1" }
}

override_data {
  target = data.google_monitoring_notification_channel.slack
  values = { name = "projects/p/notificationChannels/1" }
}

variables {
  project_id      = "p"
  modal_workspace = "ws"
}

run "stt_api_service" {
  command = apply

  assert {
    condition     = local.stt_api_image == "us-central1-docker.pkg.dev/p/models/stt-a-qwen3-asr-diar-api:0.3.0"
    error_message = "the STT API service runs its own image from the models repo (services/stt_api/cloudbuild.yaml)"
  }
  assert {
    condition     = module.stt_api.service_name == "stt-a-qwen3-asr-diar-api"
    error_message = "the STT API service name must be stt-a-qwen3-asr-diar-api"
  }
  assert {
    condition     = google_storage_bucket_iam_member.stt_api_create.bucket == "p-stt-audio" && google_storage_bucket_iam_member.stt_api_create.role == "roles/storage.objectCreator" && google_storage_bucket_iam_member.stt_api_create.member == "serviceAccount:${module.stt_api.service_account_email}"
    error_message = "the STT API SA may only create objects in the audio bucket"
  }
  assert {
    condition     = google_service_account_iam_member.stt_api_sign.role == "roles/iam.serviceAccountTokenCreator" && google_service_account_iam_member.stt_api_sign.member == "serviceAccount:${module.stt_api.service_account_email}" && endswith(google_service_account_iam_member.stt_api_sign.service_account_id, "/${module.stt_api.service_account_email}")
    error_message = "the STT API SA must sign blobs as itself only"
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.stt_api_gateway.role == "roles/run.invoker"
    error_message = "only the gateway SA may call the STT API service"
  }
  assert {
    condition = local.stt_api_env == {
      AUDIO_BUCKET = "p-stt-audio"
      SA_EMAIL     = module.stt_api.service_account_email
      IMAGE_TAG    = "0.2.5"
      TARGET       = module.model.proxy_url
      PLATFORMS    = "modal,vertex,runpod"
    }
    error_message = "the STT API service calls the GPU through the CORS proxy; a path prefix picks the platform"
  }
  assert {
    condition     = module.model.proxy_extra_invoker_count == 1
    error_message = "the STT API SA may call the CORS proxy"
  }
  assert {
    condition     = google_storage_bucket_iam_member.stt_api_read.bucket == "p-stt-audio" && google_storage_bucket_iam_member.stt_api_read.role == "roles/storage.objectViewer" && google_storage_bucket_iam_member.stt_api_read.member == "serviceAccount:${module.stt_api.service_account_email}"
    error_message = "the STT API SA must list and read the audio bucket"
  }
  assert {
    condition     = google_storage_bucket_iam_member.stt_api_names.role == "roles/storage.objectUser" && google_storage_bucket_iam_member.stt_api_names.condition[0].expression == "resource.name.startsWith(\"projects/_/buckets/p-stt-audio/objects/files/\") && (resource.name.endsWith(\".names.json\") || resource.name.endsWith(\"/reference.json\"))"
    error_message = "the STT API SA may replace only the speaker names files (*.names.json) and the references"
  }
}
