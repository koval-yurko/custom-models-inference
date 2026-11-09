locals {
  gpu = var.gpu_type != null
}

resource "google_service_account" "this" {
  project = var.project_id
  # SA IDs are 6-30 chars. Longer names get 25 chars + a hash, so names with the same prefix do not collide.
  account_id   = length(var.name) <= 30 ? var.name : "${substr(var.name, 0, 25)}-${substr(sha256(var.name), 0, 4)}"
  display_name = "Cloud Run model service ${var.name}"
}

resource "google_cloud_run_v2_service" "this" {
  project             = var.project_id
  location            = var.region
  name                = var.name
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.this.email
    max_instance_request_concurrency = var.concurrency
    timeout                          = var.timeout
    gpu_zonal_redundancy_disabled    = local.gpu ? true : null

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    dynamic "node_selector" {
      for_each = local.gpu ? [var.gpu_type] : []
      content {
        accelerator = node_selector.value
      }
    }

    containers {
      image = var.image
      args  = var.args

      ports {
        container_port = var.port
      }

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      resources {
        limits = merge(
          { cpu = var.cpu, memory = var.memory },
          local.gpu ? { "nvidia.com/gpu" = "1" } : {},
        )
        # GPU needs instance-based billing; CPU uses request-based billing so idle costs nothing.
        cpu_idle          = !local.gpu
        startup_cpu_boost = true
      }

      startup_probe {
        period_seconds    = 10
        failure_threshold = var.startup_failure_threshold

        dynamic "http_get" {
          for_each = var.startup_probe_path != null ? [var.startup_probe_path] : []
          content {
            path = http_get.value
            port = var.port
          }
        }

        dynamic "tcp_socket" {
          for_each = var.startup_probe_path == null ? [1] : []
          content {
            port = var.port
          }
        }
      }

      dynamic "volume_mounts" {
        for_each = var.weights_bucket != null ? [1] : []
        content {
          name       = "weights"
          mount_path = "/models"
        }
      }
    }

    dynamic "volumes" {
      for_each = var.weights_bucket != null ? [var.weights_bucket] : []
      content {
        name = "weights"
        gcs {
          bucket    = volumes.value
          read_only = true
        }
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  for_each = toset(var.invokers)

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = each.value
}

resource "google_storage_bucket_iam_member" "weights" {
  count = var.weights_bucket != null ? 1 : 0

  bucket = var.weights_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.this.email}"
}
