mock_provider "google" {}

variables {
  project_id = "p"
  region     = "us-central1"
  name       = "llm-a-gemma4-12b"
  spec = {
    image        = { stock = "vllm/vllm-openai:v0.33.0" }
    args         = ["--model={model}", "--served-model-name=gemma-4-12b", "--max-model-len=32768", "--host=0.0.0.0", "--port=8080"]
    env          = {}
    port         = 8080
    health_route = "/health"
    routes       = ["/v1/chat/completions"]
    gpu          = "L4"
    max_replicas = 1
    idle_seconds = 300
    weights      = { hf_repo = "google/gemma-4-12B-it-qat-w4a16-ct", revision = null, gcs_dir = "gemma-4-12b-it-qat-w4a16" }
  }
  options = {
    name                  = "llm-a-gemma4-12b-vllm-vertex"
    machine_type          = "g2-standard-12"
    shared_memory_size_mb = 16384
    deployment_timeout    = "1800s"
    extra_args            = ["--load-format=runai_streamer", "--kv-cache-dtype=fp8"]
    predict_route         = "/v1/chat/completions"
  }
}

run "same_upload_as_today" {
  command = apply

  assert {
    condition     = alltrue([for a in ["--model=$(AIP_STORAGE_URI)", "--load-format=runai_streamer", "--kv-cache-dtype=fp8"] : contains(output.vertex.model_upload.model.containerSpec.args, a)])
    error_message = "the args must hold the model path and the vertex extra args"
  }
  assert {
    condition     = output.vertex.model_upload.model.containerSpec.imageUri == "us-central1-docker.pkg.dev/p/dockerhub/vllm/vllm-openai:v0.33.0"
    error_message = "a stock image goes through the dockerhub proxy repo"
  }
  assert {
    condition     = output.vertex.model_upload.model.containerSpec.predictRoute == "/v1/chat/completions"
    error_message = "predict_route must stay"
  }
  assert {
    condition     = contains(output.vertex.model_upload.model.containerSpec.env, { name = "HF_HUB_OFFLINE", value = "1" }) && !contains([for e in output.vertex.model_upload.model.containerSpec.env : e.name], "SETUP_PLATFORM")
    error_message = "vertex reads the weights from GCS: HF_HUB_OFFLINE=1"
  }
  assert {
    condition     = output.vertex.name == "llm-a-gemma4-12b-vllm-vertex"
    error_message = "options.name keeps the current Vertex AI name (the endpoint ID is a hash of it)"
  }
  assert {
    condition     = output.vertex.model_upload.model.artifactUri == "gs://p-models/gemma-4-12b-it-qat-w4a16/"
    error_message = "the weights come from the weights bucket"
  }
  assert {
    condition     = output.vertex.model_upload.model.containerSpec.sharedMemorySizeMb == "16384" && output.vertex.deployed_model.dedicatedResources.machineSpec.machineType == "g2-standard-12"
    error_message = "machine options must pass through"
  }
}

run "scale_to_zero" {
  command = apply

  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.minReplicaCount == 0 && output.vertex.deployed_model.dedicatedResources.maxReplicaCount == 1
    error_message = "0 to max_replicas"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.scaleToZeroSpec.idleScaledownPeriod == "300s"
    error_message = "idle_seconds -> idleScaledownPeriod"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.machineSpec.acceleratorType == "NVIDIA_L4"
    error_message = "gpu L4 -> NVIDIA_L4"
  }
}

run "target_raw_predict" {
  command = apply

  assert {
    condition     = output.target.append_path == false && endswith(output.target.url, ":rawPredict")
    error_message = "with predict_route the target is the fixed :rawPredict URL"
  }
  assert {
    condition     = output.target.post_apply == "vertex" && output.target.auth == "google" && output.target.id == "vertex" && output.target.deadline == 300
    error_message = "target fields"
  }
}

run "target_invoke_without_predict_route" {
  command = apply

  variables {
    options = { name = "llm-a-gemma4-12b-vllm-vertex" }
  }

  assert {
    condition     = output.target.append_path == true && endswith(output.target.url, "/invoke")
    error_message = "without predict_route the target is the :invoke base"
  }
  assert {
    condition     = output.vertex.invoke_routes == true
    error_message = "without predict_route the upload uses invoke routes"
  }
}

run "stock_image_without_namespace" {
  command = plan

  variables {
    spec = { image = { stock = "python:3.13" }, args = [], health_route = "/health", routes = ["/x"], gpu = null }
  }

  assert {
    condition     = output.vertex.model_upload.model.containerSpec.imageUri == "us-central1-docker.pkg.dev/p/dockerhub/library/python:3.13"
    error_message = "a Docker Hub image without a namespace gets library/"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.machineSpec.acceleratorType == null
    error_message = "gpu null -> CPU"
  }
}

run "own_image" {
  command = plan

  variables {
    spec = { image = { own = "llm-b:1" }, args = [], health_route = "/health", routes = ["/x"], gpu = "L4" }
  }

  assert {
    condition     = output.vertex.model_upload.model.containerSpec.imageUri == "us-central1-docker.pkg.dev/p/models/llm-b:1"
    error_message = "an own image comes from the models repo"
  }
  assert {
    condition     = contains(output.vertex.model_upload.model.containerSpec.env, { name = "SETUP_PLATFORM", value = "vertex" })
    error_message = "an own image gets SETUP_PLATFORM (container contract)"
  }
}

run "unknown_gpu_fails" {
  command = plan

  variables {
    spec = { image = { own = "llm-b:1" }, args = [], health_route = "/health", routes = ["/x"], gpu = "H100" }
  }
  expect_failures = [output.target]
}
