mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "p"
}

run "custom_container_on_vertex" {
  command = apply

  assert {
    condition     = output.vertex.model_upload.model.containerSpec.imageUri == "us-central1-docker.pkg.dev/p/models/stt-a-qwen3-asr-diar:0.1.4"
    error_message = "the image must come from the models repo with the image_tag"
  }
  assert {
    condition     = output.vertex.model_upload.model.containerSpec.predictRoute == "/v1beta/interactions" && output.vertex.model_upload.model.containerSpec.invokeRoutePrefix == null
    error_message = ":rawPredict must reach /v1beta/interactions"
  }
  assert {
    condition     = output.vertex.model_upload.model.artifactUri == "gs://p-models/stt-a-qwen3-asr-diar/"
    error_message = "AIP_STORAGE_URI must point to the folder with asr/, aligner/ and pyannote/"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.minReplicaCount == 0
    error_message = "the endpoint must scale to 0"
  }
  assert {
    condition     = contains(output.vertex.model_upload.model.containerSpec.env, { name = "AUDIO_BUCKET", value = "p-stt-audio" })
    error_message = "the app must know the audio bucket (it accepts gs:// only from it)"
  }
  assert {
    condition     = google_storage_bucket_iam_member.model_audio.bucket == "p-stt-audio" && google_storage_bucket_iam_member.model_audio.role == "roles/storage.objectViewer" && google_storage_bucket_iam_member.model_audio.member == "serviceAccount:${module.model.service_account_email}"
    error_message = "the model SA must read the audio bucket, and only read it"
  }
}

run "setup_record" {
  command = plan

  assert {
    condition = alltrue([for e in [
      { name = "SETUP_ASR", value = "Qwen3-ASR-1.7B" },
      { name = "SETUP_ALIGNER", value = "Qwen3-ForcedAligner-0.6B" },
      { name = "SETUP_DIARIZATION", value = "pyannote/speaker-diarization-community-1" },
      { name = "SETUP_IMAGE_TAG", value = "0.1.4" },
    ] : contains(output.vertex.model_upload.model.containerSpec.env, e)])
    error_message = "the GPU service needs the SETUP_* env: each answer records the setup that made it"
  }
}
