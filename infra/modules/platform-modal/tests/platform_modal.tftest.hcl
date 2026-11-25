variables {
  project_id = "p"
  region     = "us-central1"
  name       = "stt-a-qwen3-asr-diar"
  spec = {
    image        = { own = "stt-a-qwen3-asr-diar:0.2.4" }
    args         = []
    env          = { AUDIO_BUCKET = "b" }
    port         = 8080
    health_route = "/health"
    routes       = ["/v1beta/interactions"]
    gpu          = "L4"
    max_replicas = 1
    idle_seconds = 300
    weights      = { hf_repo = "Qwen/Qwen3-ASR-1.7B", gcs_dir = "stt-a-qwen3-asr-diar" }
  }
  options = {
    workspace = "ws"
    command   = ["python3", "-m", "speech_engine.main"]
    workdir   = "/srv"
    volume    = "stt-a-weights"
    hf_repos  = { asr = "Qwen/Qwen3-ASR-1.7B" }
  }
}

run "target" {
  command = plan

  assert {
    condition     = output.target.url == "https://ws--stt-a-qwen3-asr-diar.modal.run" && output.target.auth == "modal" && output.target.post_apply == "modal"
    error_message = "the URL is <workspace>--<app>.modal.run; the proxy sends the Modal key; modal.py deploys"
  }
  assert {
    condition     = output.target.append_path && output.target.cold_start == "retry-429" && output.target.deadline == 300
    error_message = "route appended; the UI retries on the proxy 429"
  }
}

run "modal_spec" {
  command = plan

  assert {
    condition     = output.modal.image == "us-central1-docker.pkg.dev/p/models/stt-a-qwen3-asr-diar:0.2.4" && output.modal.app == "stt-a-qwen3-asr-diar"
    error_message = "own image from the models repo; the app name is the model name"
  }
  assert {
    condition     = output.modal.env == { AUDIO_BUCKET = "b", PORT = "8080", HF_HUB_OFFLINE = "1", SETUP_PLATFORM = "modal", PYTHONFAULTHANDLER = "1", MODEL = "/models/stt-a-qwen3-asr-diar" }
    error_message = "the container contract: PORT, MODEL (the Volume path) and SETUP_PLATFORM"
  }
  assert {
    condition     = output.modal.gpus == ["L4", "A10"] && output.modal.cpu == 4 && output.modal.memory_mb == 32768 && output.modal.idle_seconds == 300 && output.modal.max_containers == 1
    error_message = "defaults: L4 then A10, 4 cores, 32 GiB; the spec idle time and max replicas"
  }
  assert {
    condition     = output.modal.volume == "stt-a-weights" && output.modal.weights_dir == "stt-a-qwen3-asr-diar" && output.modal.command == ["python3", "-m", "speech_engine.main"]
    error_message = "volume, weights folder and start command from the options"
  }
}

run "idle_capped_at_20_min" {
  command = plan
  variables {
    spec = {
      image        = { own = "x:1" }
      args         = []
      health_route = "/health"
      routes       = ["/v1/x"]
      idle_seconds = 3600
    }
  }

  assert {
    condition     = output.modal.idle_seconds == 1200 && output.modal.env.PORT == "8080" && !contains(keys(output.modal.env), "MODEL")
    error_message = "scaledown_window max is 20 min; no MODEL without weights"
  }
}

run "stock_image_rejected" {
  command = plan
  variables {
    spec = {
      image        = { stock = "vllm/vllm-openai:v0.33.0" }
      args         = []
      health_route = "/health"
      routes       = ["/v1/x"]
    }
  }
  expect_failures = [output.target]
}

run "command_required" {
  command = plan
  variables {
    options = { workspace = "ws" }
  }
  expect_failures = [output.target]
}
