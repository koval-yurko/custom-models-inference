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
    name                  = "llm-a-gemma4-12b-vllm"
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
    condition     = output.vertex.name == "llm-a-gemma4-12b-vllm"
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
    options = { name = "llm-a-gemma4-12b-vllm" }
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

# The checks below came with the code of infra/modules/vertex-model (phase 6).
run "dedicated_private_endpoint" {
  command = plan

  assert {
    condition     = google_vertex_ai_endpoint.this.dedicated_endpoint_enabled == true && can(regex("^[1-9][0-9]{0,9}$", google_vertex_ai_endpoint.this.name))
    error_message = "the endpoint must be dedicated, with a numeric ID (max 10 digits, no leading zero)"
  }
  assert {
    condition     = google_vertex_ai_endpoint.this.network == null && length(google_vertex_ai_endpoint.this.private_service_connect_config) == 0
    error_message = "no VPC peering or PSC: the endpoint is reached through IAM-checked Vertex AI DNS"
  }
  assert {
    condition     = output.vertex.deployed_model.enableContainerLogging == true && output.vertex.deployed_model.dedicatedResources.initialReplicaCount == 1
    error_message = "container logs on (scale-alerts reads them); scale to zero needs initialReplicaCount 1"
  }
  assert {
    condition     = length(google_storage_bucket_iam_member.weights) == 1 && google_storage_bucket_iam_member.weights[0].bucket == "p-models" && google_storage_bucket_iam_member.weights[0].role == "roles/storage.objectViewer"
    error_message = "the model SA reads the weights bucket, and only reads it"
  }
  assert {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", google_service_account.this.account_id))
    error_message = "the SA account_id must match the GCP pattern"
  }
}

run "long_name_gives_short_sa_id" {
  command = plan

  variables {
    options = { name = "a-very-long-model-name-with-more-than-30-chars" }
  }

  assert {
    condition     = length(google_service_account.this.account_id) == 30 && can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", google_service_account.this.account_id))
    error_message = "a long name gives 25 chars + a hash"
  }
}

run "no_weights" {
  command = plan

  variables {
    spec = { image = { own = "llm-b:1" }, args = [], health_route = "/health", routes = ["/x"], gpu = "L4" }
  }

  assert {
    condition     = output.vertex.model_upload.model.artifactUri == null && length(google_storage_bucket_iam_member.weights) == 0
    error_message = "no artifactUri and no bucket IAM without weights"
  }
}

run "rejects_aip_env" {
  command = plan

  variables {
    options = { name = "llm-a-gemma4-12b-vllm", env = { AIP_HTTP_PORT = "9000" } }
  }
  expect_failures = [google_vertex_ai_endpoint.this]
}

run "rejects_idle_below_300s" {
  command = plan

  variables {
    spec = { image = { own = "llm-b:1" }, args = [], health_route = "/health", routes = ["/x"], gpu = "L4", idle_seconds = 60 }
  }
  expect_failures = [google_vertex_ai_endpoint.this]
}
