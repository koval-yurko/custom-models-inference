mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "p"
}

run "upload_service" {
  command = apply

  assert {
    condition     = module.upload.service_name == "stt-a-qwen3-asr-diar-files"
    error_message = "the files service name must be stt-a-qwen3-asr-diar-files"
  }
  assert {
    condition     = google_storage_bucket_iam_member.upload_create.bucket == "p-stt-audio" && google_storage_bucket_iam_member.upload_create.role == "roles/storage.objectCreator" && google_storage_bucket_iam_member.upload_create.member == "serviceAccount:${module.upload.service_account_email}"
    error_message = "the upload SA may only create objects in the audio bucket"
  }
  assert {
    condition     = google_service_account_iam_member.upload_sign.role == "roles/iam.serviceAccountTokenCreator" && google_service_account_iam_member.upload_sign.member == "serviceAccount:${module.upload.service_account_email}" && endswith(google_service_account_iam_member.upload_sign.service_account_id, "/${module.upload.service_account_email}")
    error_message = "the upload SA must sign blobs as itself only"
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.upload_gateway.role == "roles/run.invoker" && google_cloud_run_v2_service_iam_member.upload_gateway.member == "serviceAccount:${google_service_account.gateway.email}"
    error_message = "only the gateway SA may call the upload service"
  }
  assert {
    condition = local.upload_env == {
      AUDIO_BUCKET = "p-stt-audio"
      SA_EMAIL     = module.upload.service_account_email
      IMAGE_TAG    = "0.1.3"
      TARGET       = "https://${module.model.endpoint_dns}/v1/projects/p/locations/us-central1/endpoints/${module.model.endpoint_id}:rawPredict"
    }
    error_message = "the files service needs AUDIO_BUCKET, SA_EMAIL, IMAGE_TAG and the :rawPredict TARGET"
  }
  assert {
    condition     = local.upload_env.TARGET == local.raw_predict_url
    error_message = "the files service and the CORS proxy must call the same :rawPredict URL"
  }
  assert {
    condition     = google_storage_bucket_iam_member.upload_read.bucket == "p-stt-audio" && google_storage_bucket_iam_member.upload_read.role == "roles/storage.objectViewer" && google_storage_bucket_iam_member.upload_read.member == "serviceAccount:${module.upload.service_account_email}"
    error_message = "the files SA must list and read the audio bucket"
  }
  assert {
    condition     = google_storage_bucket_iam_member.upload_names.role == "roles/storage.objectUser" && google_storage_bucket_iam_member.upload_names.condition[0].expression == "resource.name.startsWith(\"projects/_/buckets/p-stt-audio/objects/files/\") && resource.name.endsWith(\".names.json\")"
    error_message = "the files SA may replace only the speaker names files (*.names.json)"
  }
  assert {
    condition     = google_project_iam_member.upload_predict.role == "roles/aiplatform.user" && google_project_iam_member.upload_predict.member == "serviceAccount:${module.upload.service_account_email}"
    error_message = "the files SA must call Vertex AI :rawPredict"
  }
}
