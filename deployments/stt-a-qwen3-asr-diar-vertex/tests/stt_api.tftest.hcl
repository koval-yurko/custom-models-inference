mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "p"
}

run "stt_api_service" {
  command = apply

  assert {
    condition     = local.stt_api_image == "us-central1-docker.pkg.dev/p/models/stt-a-qwen3-asr-diar-api:0.2.0"
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
    condition     = google_cloud_run_v2_service_iam_member.stt_api_gateway.role == "roles/run.invoker" && google_cloud_run_v2_service_iam_member.stt_api_gateway.member == "serviceAccount:${google_service_account.gateway.email}"
    error_message = "only the gateway SA may call the STT API service"
  }
  assert {
    condition = local.stt_api_env == {
      AUDIO_BUCKET = "p-stt-audio"
      SA_EMAIL     = module.stt_api.service_account_email
      IMAGE_TAG    = "0.1.4"
      TARGET       = "https://${module.model.endpoint_dns}/v1/projects/p/locations/us-central1/endpoints/${module.model.endpoint_id}:rawPredict"
    }
    error_message = "the STT API service needs AUDIO_BUCKET, SA_EMAIL, IMAGE_TAG and the :rawPredict TARGET"
  }
  assert {
    condition     = local.stt_api_env.TARGET == local.raw_predict_url
    error_message = "the STT API service and the CORS proxy must call the same :rawPredict URL"
  }
  assert {
    condition     = google_storage_bucket_iam_member.stt_api_read.bucket == "p-stt-audio" && google_storage_bucket_iam_member.stt_api_read.role == "roles/storage.objectViewer" && google_storage_bucket_iam_member.stt_api_read.member == "serviceAccount:${module.stt_api.service_account_email}"
    error_message = "the STT API SA must list and read the audio bucket"
  }
  assert {
    condition     = google_storage_bucket_iam_member.stt_api_names.role == "roles/storage.objectUser" && google_storage_bucket_iam_member.stt_api_names.condition[0].expression == "resource.name.startsWith(\"projects/_/buckets/p-stt-audio/objects/files/\") && (resource.name.endsWith(\".names.json\") || resource.name.endsWith(\"/reference.json\"))"
    error_message = "the STT API SA may replace only the speaker names files (*.names.json) and the references"
  }
  assert {
    condition     = google_project_iam_member.stt_api_predict.role == "roles/aiplatform.user" && google_project_iam_member.stt_api_predict.member == "serviceAccount:${module.stt_api.service_account_email}"
    error_message = "the STT API SA must call Vertex AI :rawPredict"
  }
}
