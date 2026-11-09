mock_provider "google" {}

variables {
  project_id = "p"
  region     = "europe-west4"
  name       = "tts-a-kokoro-cpu"
  image      = "img"
  invokers   = ["user:a@b.c"]
}

run "cpu_only_defaults" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.this.template[0].scaling[0].min_instance_count == 0
    error_message = "min instances must be 0"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.template[0].scaling[0].max_instance_count == 1
    error_message = "default max instances must be 1"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.deletion_protection == false
    error_message = "deletion protection must be off so destroy works"
  }
  assert {
    condition     = length(google_cloud_run_v2_service.this.template[0].node_selector) == 0
    error_message = "CPU service must not have a node selector"
  }
  assert {
    condition     = length(google_cloud_run_v2_service.this.template[0].volumes) == 0
    error_message = "no volume without weights_bucket"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.template[0].containers[0].resources[0].cpu_idle == true
    error_message = "CPU service must use request-based billing"
  }
  assert {
    condition     = length(google_storage_bucket_iam_member.weights) == 0
    error_message = "no bucket IAM without weights_bucket"
  }
}

run "gpu_service" {
  command = plan

  variables {
    gpu_type = "nvidia-l4"
    memory   = "16Gi"
  }

  assert {
    condition     = google_cloud_run_v2_service.this.template[0].node_selector[0].accelerator == "nvidia-l4"
    error_message = "accelerator must be set"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.template[0].containers[0].resources[0].limits["nvidia.com/gpu"] == "1"
    error_message = "GPU limit must be 1"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.template[0].gpu_zonal_redundancy_disabled == true
    error_message = "zonal redundancy must be off"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.template[0].containers[0].resources[0].cpu_idle == false
    error_message = "GPU service needs instance-based billing"
  }
}

run "weights_volume" {
  command = plan

  variables {
    weights_bucket = "w"
  }

  assert {
    condition     = length(google_cloud_run_v2_service.this.template[0].volumes) == 1
    error_message = "one volume expected"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.template[0].volumes[0].gcs[0].bucket == "w"
    error_message = "volume must use the weights bucket"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.template[0].volumes[0].gcs[0].read_only == true
    error_message = "volume must be read-only"
  }
  assert {
    condition     = google_cloud_run_v2_service.this.template[0].containers[0].volume_mounts[0].mount_path == "/models"
    error_message = "mount path must be /models"
  }
  assert {
    condition     = length(google_storage_bucket_iam_member.weights) == 1 && google_storage_bucket_iam_member.weights[0].role == "roles/storage.objectViewer"
    error_message = "SA needs objectViewer on the bucket"
  }
}

run "http_probe" {
  command = plan

  variables {
    startup_probe_path = "/health"
  }

  assert {
    condition     = google_cloud_run_v2_service.this.template[0].containers[0].startup_probe[0].http_get[0].path == "/health"
    error_message = "HTTP probe path must be /health"
  }
  assert {
    condition     = length(google_cloud_run_v2_service.this.template[0].containers[0].startup_probe[0].tcp_socket) == 0
    error_message = "no TCP probe when an HTTP path is set"
  }
}

run "tcp_probe_default" {
  command = plan

  assert {
    condition     = length(google_cloud_run_v2_service.this.template[0].containers[0].startup_probe[0].tcp_socket) == 1
    error_message = "default probe must be TCP"
  }
  assert {
    condition     = length(google_cloud_run_v2_service.this.template[0].containers[0].startup_probe[0].http_get) == 0
    error_message = "no HTTP probe by default"
  }
}

run "invokers_bound" {
  command = plan

  variables {
    invokers = ["user:a@b.c", "serviceAccount:x@p.iam.gserviceaccount.com"]
  }

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.invoker) == 2
    error_message = "one binding per invoker"
  }
  assert {
    condition     = alltrue([for m in google_cloud_run_v2_service_iam_member.invoker : m.role == "roles/run.invoker"])
    error_message = "all bindings must be run.invoker"
  }
}

run "rejects_all_users" {
  command = plan

  variables {
    invokers = ["allUsers"]
  }

  expect_failures = [var.invokers]
}

run "rejects_all_authenticated_users" {
  command = plan

  variables {
    invokers = ["user:a@b.c", "allAuthenticatedUsers"]
  }

  expect_failures = [var.invokers]
}

run "long_name_gives_valid_sa_id" {
  command = plan

  variables {
    name = "tts-b-qwen3-tts-1p7b-vllm-omni-service"
  }

  assert {
    condition     = length(google_service_account.this.account_id) <= 30
    error_message = "SA account_id must be at most 30 characters"
  }
  assert {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", google_service_account.this.account_id))
    error_message = "SA account_id must match the GCP pattern"
  }
}

run "short_name_keeps_sa_id" {
  command = plan

  assert {
    condition     = google_service_account.this.account_id == "tts-a-kokoro-cpu"
    error_message = "names of 30 chars or less are used as the SA ID as they are"
  }
}

run "long_names_with_same_prefix_get_different_sa_ids_a" {
  command = plan

  variables {
    name = "llm-b-qwen35-9b-fastapi-custom-a"
  }

  assert {
    condition     = google_service_account.this.account_id == "llm-b-qwen35-9b-fastapi-c-201d"
    error_message = "long names get the first 25 chars plus 4 hash chars"
  }
}

run "long_names_with_same_prefix_get_different_sa_ids_b" {
  command = plan

  variables {
    name = "llm-b-qwen35-9b-fastapi-custom-b"
  }

  assert {
    condition     = google_service_account.this.account_id == "llm-b-qwen35-9b-fastapi-c-fdfd"
    error_message = "a different long name with the same prefix must get a different SA ID"
  }
}

run "rejects_short_name" {
  command = plan

  variables {
    name = "tts"
  }

  expect_failures = [var.name]
}

run "rejects_uppercase_name" {
  command = plan

  variables {
    name = "TTS-A-kokoro"
  }

  expect_failures = [var.name]
}

run "rejects_name_ending_with_hyphen" {
  command = plan

  variables {
    name = "tts-a-kokoro-"
  }

  expect_failures = [var.name]
}

run "rejects_name_over_49_chars" {
  command = plan

  variables {
    name = "a234567890123456789012345678901234567890123456789x"
  }

  expect_failures = [var.name]
}
