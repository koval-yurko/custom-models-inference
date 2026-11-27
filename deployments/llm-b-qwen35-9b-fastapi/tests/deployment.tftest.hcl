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
    condition     = output.vertex.model_upload.model.containerSpec.imageUri == "us-central1-docker.pkg.dev/p/models/llm-b-qwen35-9b-fastapi:0.2.3"
    error_message = "the image must come from the models repo with the image_tag"
  }
  assert {
    condition     = output.vertex.name == "llm-b-qwen35-9b-fastapi"
    error_message = "the Vertex AI name stays (the endpoint ID is a hash of it, moved.tf keeps the endpoint)"
  }
  assert {
    condition     = output.vertex.model_upload.model.containerSpec.invokeRoutePrefix == "/*" && output.vertex.model_upload.model.containerSpec.predictRoute == null
    error_message = "every app.py route must be reachable through :invoke"
  }
  assert {
    condition     = output.vertex.model_upload.model.artifactUri == "gs://p-models/qwen3.5-9b-fp8/"
    error_message = "AIP_STORAGE_URI must point to the weights folder of the weights-copy job"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.minReplicaCount == 0 && output.vertex.deployed_model.dedicatedResources.machineSpec.machineType == "g2-standard-8" && output.vertex.model_upload.model.containerSpec.sharedMemorySizeMb == "16384"
    error_message = "the endpoint must scale to 0 on the same machine as before"
  }
  assert {
    condition = alltrue([for e in [
      { name = "HF_HUB_OFFLINE", value = "1" },
      { name = "SERVED_MODEL_NAME", value = "qwen3.5-9b" },
      { name = "MAX_MODEL_LEN", value = "16384" },
    ] : contains(output.vertex.model_upload.model.containerSpec.env, e)]) && !contains([for e in output.vertex.model_upload.model.containerSpec.env : e.name], "KV_CACHE_DTYPE")
    error_message = "the engine env stays; Vertex AI (L4) keeps the fp8 KV cache default of app.py"
  }
  assert {
    condition     = output.targets.vertex.append_path == true && endswith(output.targets.vertex.url, "/invoke")
    error_message = "the proxy appends the route to the :invoke base"
  }
}

run "runpod_worker" {
  command = apply

  assert {
    condition     = module.model.runpod_env.MODEL == "/runpod-volume/qwen3.5-9b-fp8" && module.model.runpod_env.PORT == "8080" && module.model.runpod_env.HF_HUB_OFFLINE == "1"
    error_message = "the Runpod worker reads the weights from the volume (container contract: MODEL, PORT)"
  }
  assert {
    condition     = module.model.runpod_env.KV_CACHE_DTYPE == "auto" && module.model.runpod_env.SERVED_MODEL_NAME == "qwen3.5-9b"
    error_message = "Ampere GPUs have no native FP8: the KV cache uses the model dtype on Runpod"
  }
  assert {
    condition     = [for v in output.runpod_volumes.volumes : v.data_center] == ["EU-RO-1"] && output.runpod_volumes.dir == "qwen3.5-9b-fp8" && output.weights_gcs == "gs://p-models/qwen3.5-9b-fp8/"
    error_message = "scripts/runpod-weights.py reads the volume and the GCS source from the outputs"
  }
  assert {
    condition     = !contains(output.platforms, "runpod") || (output.targets.runpod.cold_start == "retry-429" && output.targets.runpod.auth == "runpod" && output.targets.runpod.append_path == true)
    error_message = "the Runpod target of the proxy (when runpod serves in deploy.yaml)"
  }
}

run "ui_platforms" {
  command = apply

  assert {
    condition     = tolist([for p in output.ui.platforms : p.id]) == tolist(output.platforms) && alltrue([for p in output.ui.platforms : p.cold_start == "retry-429"])
    error_message = "the tab gets a platform picker; both platforms retry a 429"
  }
  assert {
    condition     = output.ui.base_url == "${output.gateway_url}/vertex" && output.ui.type == "llm-routes" && output.ui.features.routes == ["/generate", "/extract"]
    error_message = "the default platform is the first; the panel gets the routes"
  }
}
