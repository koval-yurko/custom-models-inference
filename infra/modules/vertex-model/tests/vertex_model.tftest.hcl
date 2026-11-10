mock_provider "google" {}

variables {
  project_id     = "p"
  region         = "europe-west4"
  name           = "llm-a-gemma4-12b-vllm-vertex"
  image          = "europe-west4-docker.pkg.dev/p/dockerhub/vllm/vllm-openai:v0.33.0"
  args           = ["--model=$(AIP_STORAGE_URI)", "--load-format=runai_streamer"]
  predict_route  = "/v1/chat/completions"
  weights_bucket = "p-models"
  weights_dir    = "gemma-4-12b-it-qat-w4a16"
}

run "defaults_scale_to_zero_on_l4" {
  command = plan

  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.minReplicaCount == 0
    error_message = "min replicas must be 0"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.maxReplicaCount == 1
    error_message = "default max replicas must be 1"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.initialReplicaCount == 1
    error_message = "scale to zero needs initialReplicaCount >= 1"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.scaleToZeroSpec.idleScaledownPeriod == "300s"
    error_message = "default idle time must be the 300s minimum, not the 1 h Vertex default"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.machineSpec.machineType == "g2-standard-8" && output.vertex.deployed_model.dedicatedResources.machineSpec.acceleratorType == "NVIDIA_L4" && output.vertex.deployed_model.dedicatedResources.machineSpec.acceleratorCount == 1
    error_message = "default machine must be g2-standard-8 with 1 L4"
  }
}

run "dedicated_private_endpoint" {
  command = plan

  assert {
    condition     = google_vertex_ai_endpoint.this.dedicated_endpoint_enabled == true
    error_message = "endpoint must be dedicated"
  }
  assert {
    condition     = can(regex("^[1-9][0-9]{0,9}$", google_vertex_ai_endpoint.this.name))
    error_message = "endpoint ID must be numeric, max 10 digits, no leading zero"
  }
  assert {
    condition     = google_vertex_ai_endpoint.this.network == null && length(google_vertex_ai_endpoint.this.private_service_connect_config) == 0
    error_message = "no VPC peering or PSC: the endpoint is reached through IAM-checked Vertex AI DNS"
  }
}

run "weights_from_aip_storage_uri" {
  command = plan

  assert {
    condition     = output.vertex.model_upload.model.artifactUri == "gs://p-models/gemma-4-12b-it-qat-w4a16/"
    error_message = "artifactUri must point at the weights folder (it becomes AIP_STORAGE_URI)"
  }
  assert {
    condition     = length(google_storage_bucket_iam_member.weights) == 1 && google_storage_bucket_iam_member.weights[0].role == "roles/storage.objectViewer" && google_storage_bucket_iam_member.weights[0].bucket == "p-models"
    error_message = "SA needs objectViewer on the weights bucket"
  }
}

run "predict_route_contract" {
  command = plan

  assert {
    condition     = output.vertex.model_upload.model.containerSpec.predictRoute == "/v1/chat/completions" && output.vertex.model_upload.model.containerSpec.invokeRoutePrefix == null
    error_message = "predict route set, no invoke prefix"
  }
  assert {
    condition     = output.vertex.model_upload.model.containerSpec.healthRoute == "/health"
    error_message = "default health route must be /health"
  }
  assert {
    condition     = output.vertex.model_upload.model.containerSpec.ports[0].containerPort == 8080
    error_message = "default port must be 8080"
  }
}

run "invoke_routes" {
  command = plan

  variables {
    predict_route = null
    invoke_routes = true
  }

  assert {
    condition     = output.vertex.model_upload.model.containerSpec.invokeRoutePrefix == "/*" && output.vertex.model_upload.model.containerSpec.predictRoute == null
    error_message = "invoke_routes sets invokeRoutePrefix /* and no predict route"
  }
}

run "rejects_predict_route_and_invoke_routes" {
  command = plan

  variables {
    invoke_routes = true
  }

  expect_failures = [google_vertex_ai_endpoint.this]
}

run "rejects_no_route" {
  command = plan

  variables {
    predict_route = null
  }

  expect_failures = [google_vertex_ai_endpoint.this]
}

run "no_weights" {
  command = plan

  variables {
    weights_bucket = null
    weights_dir    = null
  }

  assert {
    condition     = output.vertex.model_upload.model.artifactUri == null && length(google_storage_bucket_iam_member.weights) == 0
    error_message = "no artifactUri and no bucket IAM without weights"
  }
}

run "rejects_weights_dir_without_bucket" {
  command = plan

  variables {
    weights_bucket = null
  }

  expect_failures = [google_vertex_ai_endpoint.this]
}

run "cpu_only" {
  command = plan

  variables {
    machine_type     = "n2-standard-4"
    accelerator_type = null
  }

  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.machineSpec.acceleratorType == null && output.vertex.deployed_model.dedicatedResources.machineSpec.acceleratorCount == null
    error_message = "CPU only: no accelerator fields"
  }
}

run "rejects_aip_env" {
  command = plan

  variables {
    env = { AIP_HTTP_PORT = "9000" }
  }

  expect_failures = [var.env]
}

run "rejects_image_outside_artifact_registry" {
  command = plan

  variables {
    image = "docker.io/vllm/vllm-openai:v0.33.0"
  }

  expect_failures = [var.image]
}

run "rejects_idle_below_300s" {
  command = plan

  variables {
    idle_scaledown_period = "60s"
  }

  expect_failures = [var.idle_scaledown_period]
}

run "rejects_idle_above_28800s" {
  command = plan

  variables {
    idle_scaledown_period = "28801s"
  }

  expect_failures = [var.idle_scaledown_period]
}

run "rejects_zero_max_replicas" {
  command = plan

  variables {
    max_replica_count = 0
  }

  expect_failures = [var.max_replica_count]
}

run "long_name_gives_valid_sa_id" {
  command = plan

  assert {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", google_service_account.this.account_id))
    error_message = "SA account_id must match the GCP pattern"
  }
}

run "rejects_uppercase_name" {
  command = plan

  variables {
    name = "LLM-A-vertex"
  }

  expect_failures = [var.name]
}
