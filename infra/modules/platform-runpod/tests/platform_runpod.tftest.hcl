mock_provider "runpod" {
  mock_resource "runpod_serverless_endpoint" {
    defaults = { request_urls = { base = "https://ep1.api.runpod.ai" } }
  }
}

variables {
  project_id = "p"
  region     = "us-central1"
  name       = "llm-a-gemma4-12b"
  spec = {
    image        = { stock = "vllm/vllm-openai:v0.33.0" }
    args         = ["--model={model}", "--served-model-name=gemma-4-12b", "--port=8080"]
    env          = {}
    port         = 8080
    health_route = "/health"
    routes       = ["/v1/chat/completions"]
    gpu          = "L4"
    max_replicas = 1
    idle_seconds = 300
    weights      = { hf_repo = "google/gemma-4-12B-it-qat-w4a16-ct", revision = "1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee", gcs_dir = "x" }
  }
  options = { extra_args = ["--enforce-eager"] }
}

run "template" {
  command = apply

  assert {
    condition     = runpod_template.this.args == "--model=google/gemma-4-12B-it-qat-w4a16-ct --served-model-name=gemma-4-12b --port=8080 --enforce-eager --revision=1d2c2d7f2466070e69d6fb3fd5ce9a7d75f2f6ee"
    error_message = "args: spec args, extra args, then the revision; {model} is the Hugging Face repo"
  }
  assert {
    condition     = runpod_template.this.image == "vllm/vllm-openai:v0.33.0" && runpod_template.this.serverless == true
    error_message = "stock image from Docker Hub, serverless template"
  }
  assert {
    condition     = runpod_template.this.ports == tolist(["8080/http"]) && runpod_template.this.disk == 60
    error_message = "port of the spec, 60 GB disk"
  }
  assert {
    condition     = runpod_template.this.env == tomap({ HF_HUB_OFFLINE = "0", PORT = "8080", PORT_HEALTH = "8080", HEALTH_CHECK_PATH = "/health" })
    error_message = "env: download weights, health port and path"
  }
  assert {
    condition     = runpod_template.this.name == "llm-a-gemma4-12b"
    error_message = "template name is the base name"
  }
}

run "endpoint" {
  command = apply

  assert {
    condition     = runpod_serverless_endpoint.this.endpoint_type == "LOAD_BALANCER" && runpod_serverless_endpoint.this.scaling_type == "REQUEST_COUNT" && runpod_serverless_endpoint.this.scaling_value == 4
    error_message = "load balancing endpoint, request count scaling, 4"
  }
  assert {
    condition     = runpod_serverless_endpoint.this.gpu_pools == tolist(["AMPERE_24"]) && runpod_serverless_endpoint.this.gpu_count == 1
    error_message = "default pool AMPERE_24, 1 GPU"
  }
  assert {
    condition     = runpod_serverless_endpoint.this.workers_min == 0 && runpod_serverless_endpoint.this.workers_max == 1 && runpod_serverless_endpoint.this.idle_timeout == 300
    error_message = "scale to 0, max_replicas, idle_seconds"
  }
  assert {
    condition     = runpod_serverless_endpoint.this.flashboot == "FLASHBOOT" && runpod_serverless_endpoint.this.template_id == runpod_template.this.id
    error_message = "flashboot on, endpoint from the template"
  }
}

run "target" {
  command = apply

  assert {
    condition     = output.target == { id = "runpod", label = "Runpod", url = "https://ep1.api.runpod.ai", append_path = true, auth = "runpod", cold_start = "retry-429", deadline = 300, post_apply = null }
    error_message = "the common target output"
  }
}

run "options_override" {
  command = apply

  variables {
    options = { gpu_pools = ["ADA_24"], excluded_types = ["NVIDIA L40"], scaling_value = 2, disk_gb = 80, env = { A = "1" }, hf_token_secret = "hf_token", name = "other" }
  }

  assert {
    condition     = runpod_serverless_endpoint.this.gpu_pools == tolist(["ADA_24"]) && runpod_serverless_endpoint.this.excluded_types == tolist(["NVIDIA L40"]) && runpod_serverless_endpoint.this.scaling_value == 2
    error_message = "pools, excluded types and scaling value from options"
  }
  assert {
    condition     = runpod_template.this.disk == 80 && runpod_template.this.name == "other" && runpod_serverless_endpoint.this.name == "other"
    error_message = "disk and names from options"
  }
  assert {
    condition     = runpod_template.this.env["A"] == "1" && runpod_template.this.env["HF_TOKEN"] == "{{ RUNPOD_SECRET_hf_token }}"
    error_message = "options env and the Runpod secret reference for HF_TOKEN"
  }
}

run "other_port" {
  command = apply

  variables {
    spec = {
      image        = { stock = "x/y:1" }
      args         = ["--port=9000"]
      port         = 9000
      health_route = "/ping"
      routes       = ["/v1/x"]
      gpu          = "L4"
    }
    options = {}
  }

  assert {
    condition     = runpod_template.this.ports == tolist(["9000/http"]) && runpod_template.this.env["PORT"] == "9000" && runpod_template.this.env["PORT_HEALTH"] == "9000" && runpod_template.this.env["HEALTH_CHECK_PATH"] == "/ping"
    error_message = "port and health path follow the spec"
  }
}

run "revision_required" {
  command = plan

  variables {
    spec = {
      image        = { stock = "x/y:1" }
      args         = ["--model={model}"]
      health_route = "/health"
      routes       = ["/v1/x"]
      gpu          = "L4"
      weights      = { hf_repo = "a/b" }
    }
  }

  expect_failures = [runpod_template.this]
}

run "arg_with_space_fails" {
  command = plan

  variables {
    spec = {
      image        = { stock = "x/y:1" }
      args         = ["--chat-template=a b"]
      health_route = "/health"
      routes       = ["/v1/x"]
      gpu          = "L4"
    }
  }

  expect_failures = [runpod_template.this]
}

run "cpu_fails" {
  command = plan

  variables {
    spec = {
      image        = { stock = "x/y:1" }
      args         = []
      health_route = "/health"
      routes       = ["/v1/x"]
    }
  }

  expect_failures = [runpod_template.this]
}

run "own_image_fails" {
  command = plan

  variables {
    spec = {
      image        = { own = "x:1" }
      args         = []
      health_route = "/health"
      routes       = ["/v1/x"]
      gpu          = "L4"
    }
  }

  expect_failures = [runpod_template.this]
}

# The endpoint copies the template only once (template_id), so a template change must replace the endpoint.
run "before_change" {
  command = apply
}

run "template_change_replaces_endpoint" {
  command = apply

  variables {
    options = { extra_args = ["--enforce-eager", "--max-num-seqs=8"] }
  }

  assert {
    condition     = runpod_serverless_endpoint.this.id != run.before_change.endpoint_id
    error_message = "a changed template must give a new endpoint, else the workers keep the old args"
  }
}

run "arg_with_tab_fails" {
  command = plan

  variables {
    spec = {
      image        = { stock = "x/y:1" }
      args         = ["--x=a\tb"]
      health_route = "/health"
      routes       = ["/v1/x"]
      gpu          = "L4"
    }
  }

  expect_failures = [runpod_template.this]
}

run "arg_with_quote_fails" {
  command = plan

  variables {
    spec = {
      image        = { stock = "x/y:1" }
      args         = ["--x=\"a\""]
      health_route = "/health"
      routes       = ["/v1/x"]
      gpu          = "L4"
    }
  }

  expect_failures = [runpod_template.this]
}

run "arg_starting_with_brace_fails" {
  command = plan

  variables {
    spec = {
      image        = { stock = "x/y:1" }
      args         = ["{\"a\":1}"]
      health_route = "/health"
      routes       = ["/v1/x"]
      gpu          = "L4"
    }
  }

  expect_failures = [runpod_template.this]
}

run "model_without_weights_fails" {
  command = plan

  variables {
    spec = {
      image        = { stock = "x/y:1" }
      args         = ["--model={model}"]
      health_route = "/health"
      routes       = ["/v1/x"]
      gpu          = "L4"
    }
  }

  expect_failures = [runpod_template.this]
}
