mock_provider "google" {
  # The gateway module needs an https backend URL.
  mock_resource "google_cloud_run_v2_service" {
    defaults = { uri = "https://proxy" }
  }
}
mock_provider "google-beta" {}

variables {
  project_id     = "p"
  region         = "us-central1"
  gateway_region = "europe-west1"
  name           = "llm-a-gemma4-12b"
  gateway_id     = "llm-a-gemma4-vertex"
  platforms      = ["vertex"]
  spec = {
    image        = { stock = "vllm/vllm-openai:v0.33.0" }
    args         = ["--model={model}", "--served-model-name=gemma-4-12b", "--max-model-len=32768", "--host=0.0.0.0", "--port=8080"]
    health_route = "/health"
    routes       = ["/v1/chat/completions"]
    gpu          = "L4"
    weights      = { hf_repo = "google/gemma-4-12B-it-qat-w4a16-ct", gcs_dir = "gemma-4-12b-it-qat-w4a16" }
  }
  platform_options = {
    vertex = {
      name                  = "llm-a-gemma4-12b-vllm-vertex"
      machine_type          = "g2-standard-12"
      shared_memory_size_mb = 16384
      extra_args            = ["--load-format=runai_streamer", "--kv-cache-dtype=fp8"]
      predict_route         = "/v1/chat/completions"
    }
  }
}

run "vertex_only" {
  command = apply

  assert {
    condition     = output.platforms == tolist(["vertex"])
    error_message = "platforms"
  }
  assert {
    condition     = keys(output.targets) == ["vertex"]
    error_message = "one vertex target"
  }
  assert {
    condition     = output.vertex != null
    error_message = "vertex output"
  }
}

run "proxy_gets_targets_and_default" {
  command = apply

  assert {
    condition     = jsondecode(module.cors_proxy.env.TARGETS).vertex.auth == "google" && jsondecode(module.cors_proxy.env.TARGETS).vertex.append_path == false
    error_message = "the proxy gets the vertex target"
  }
  assert {
    condition     = module.cors_proxy.env.DEFAULT == "vertex"
    error_message = "the first platform is the default"
  }
}

run "gateway_paths" {
  command = apply

  assert {
    condition     = keys(output.openapi.paths) == ["/v1/chat/completions", "/vertex/v1/chat/completions"]
    error_message = "the old path and the vertex path"
  }
  assert {
    condition     = output.openapi.paths["/v1/chat/completions"].post["x-google-backend"].address == module.cors_proxy.url
    error_message = "the gateway calls the proxy"
  }
}

run "names_unchanged" {
  command = apply

  assert {
    condition     = output.vertex.name == "llm-a-gemma4-12b-vllm-vertex" && output.gateway_id == "llm-a-gemma4-vertex"
    error_message = "the Vertex AI name and the gateway ID must stay"
  }
  assert {
    condition     = output.gateway_address == "module.gateway.google_api_gateway_gateway.this"
    error_message = "gateway_address is relative to this module"
  }
}

run "rejects_empty" {
  command = plan
  variables {
    platforms = []
  }
  expect_failures = [var.platforms]
}

run "rejects_duplicates" {
  command = plan
  variables {
    platforms = ["vertex", "vertex"]
  }
  expect_failures = [var.platforms]
}

run "rejects_unsupported" {
  command = plan
  variables {
    platforms = ["runpod"]
  }
  expect_failures = [var.platforms]
}

run "rejects_two_images" {
  command = plan
  variables {
    spec = { image = { stock = "a", own = "b" }, args = [], health_route = "/health", routes = ["/x"] }
  }
  expect_failures = [var.spec]
}

run "ui_platforms" {
  command = apply

  assert {
    condition     = length(output.ui_platforms) == 1 && output.ui_platforms[0].id == "vertex" && output.ui_platforms[0].label == "Vertex AI"
    error_message = "1 ui platform per target, in the order of platforms"
  }
  assert {
    condition     = output.ui_platforms[0].base_url == "${output.gateway_url}/vertex" && output.ui_platforms[0].cold_start == "retry-429"
    error_message = "base_url is the gateway URL plus /<id>; cold_start comes from the target"
  }
}
