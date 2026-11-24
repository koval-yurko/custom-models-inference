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
  project_id = "p"
}

run "custom_container_on_vertex" {
  command = apply

  assert {
    condition     = output.vertex.model_upload.model.containerSpec.imageUri == "us-central1-docker.pkg.dev/p/models/stt-a-qwen3-asr-diar:0.2.3"
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
    condition     = contains(output.vertex.model_upload.model.containerSpec.env, { name = "AUDIO_BUCKET", value = "p-stt-audio" }) && contains(output.vertex.model_upload.model.containerSpec.env, { name = "HF_HUB_OFFLINE", value = "1" })
    error_message = "the app must know the audio bucket (the allow-list for audio URIs), and stay offline"
  }
  assert {
    condition     = google_storage_bucket_iam_member.model_audio.bucket == "p-stt-audio" && google_storage_bucket_iam_member.model_audio.role == "roles/storage.objectViewer" && google_storage_bucket_iam_member.model_audio.member == "serviceAccount:${module.model.vertex_service_account_email}"
    error_message = "the Vertex AI model SA must read the audio bucket, and only read it"
  }
  assert {
    condition     = module.model.vertex_endpoint_id != null
    error_message = "the Vertex AI endpoint stays in the facade (moved.tf)"
  }
}

run "runpod_worker" {
  command = apply

  assert {
    condition     = module.model.runpod_env.MODEL == "/runpod-volume/stt-a-qwen3-asr-diar" && module.model.runpod_env.SETUP_PLATFORM == "runpod" && module.model.runpod_env.AUDIO_BUCKET == "p-stt-audio"
    error_message = "the Runpod worker reads the weights from the volume and records its platform"
  }
  assert {
    condition     = [for v in output.runpod_volumes.volumes : v.data_center] == ["EU-CZ-1", "EU-RO-1", "EUR-IS-1"] && output.runpod_volumes.dir == "stt-a-qwen3-asr-diar" && output.weights_gcs == "gs://p-models/stt-a-qwen3-asr-diar/"
    error_message = "scripts/runpod-weights.py reads the volume and the GCS source from the outputs"
  }
  assert {
    condition     = output.targets.runpod.cold_start == "retry-429" && output.targets.runpod.auth == "runpod"
    error_message = "the Runpod target of the proxy"
  }
}

run "setup_record" {
  command = plan

  assert {
    condition = alltrue([for e in [
      { name = "SETUP_ASR", value = "Qwen3-ASR-1.7B" },
      { name = "SETUP_ALIGNER", value = "Qwen3-ForcedAligner-0.6B" },
      { name = "SETUP_DIARIZATION", value = "pyannote/speaker-diarization-community-1" },
      { name = "SETUP_IMAGE_TAG", value = "0.2.3" },
      { name = "SETUP_PLATFORM", value = "vertex" },
    ] : contains(output.vertex.model_upload.model.containerSpec.env, e)])
    error_message = "the GPU service needs the SETUP_* env: each answer records the setup that made it"
  }
}

run "ui_platforms" {
  command = apply

  assert {
    condition     = [for p in output.ui.platforms : p.id] == ["vertex", "runpod"] && alltrue([for p in output.ui.platforms : p.cold_start == "retry-429"])
    error_message = "the STT tab gets a platform picker; both platforms retry a 429"
  }
  assert {
    condition     = output.ui.base_url == "${output.gateway_url}/vertex" && output.ui.type == "stt"
    error_message = "the default platform is the first"
  }
}
