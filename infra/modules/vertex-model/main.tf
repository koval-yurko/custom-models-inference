locals {
  artifact_uri = var.weights_dir != null && var.weights_bucket != null ? "gs://${var.weights_bucket}/${trim(var.weights_dir, "/")}/" : null

  # Request bodies for the Vertex AI REST API (v1beta1). vertex.sh sends them; Terraform has no resource
  # for a custom-container model upload or deploy with scale to zero.
  model_upload = {
    model = {
      displayName = var.name
      artifactUri = local.artifact_uri
      containerSpec = {
        imageUri           = var.image
        args               = var.args
        env                = [for k, v in var.env : { name = k, value = v }]
        ports              = [{ containerPort = var.port }]
        healthRoute        = var.health_route
        predictRoute       = var.invoke_routes ? null : var.predict_route
        invokeRoutePrefix  = var.invoke_routes ? "/*" : null
        sharedMemorySizeMb = var.shared_memory_size_mb != null ? tostring(var.shared_memory_size_mb) : null
        deploymentTimeout  = var.deployment_timeout
      }
    }
  }

  deployed_model = {
    displayName    = var.name
    serviceAccount = google_service_account.this.email
    dedicatedResources = {
      machineSpec = {
        machineType      = var.machine_type
        acceleratorType  = var.accelerator_type
        acceleratorCount = var.accelerator_type != null ? var.accelerator_count : null
      }
      minReplicaCount     = 0
      maxReplicaCount     = var.max_replica_count
      initialReplicaCount = 1
      scaleToZeroSpec = {
        minScaleupPeriod    = var.min_scaleup_period
        idleScaledownPeriod = var.idle_scaledown_period
      }
    }
  }
}

resource "google_service_account" "this" {
  project = var.project_id
  # SA IDs are 6-30 chars. Longer names get 25 chars + a hash, so names with the same prefix do not collide.
  account_id   = length(var.name) <= 30 ? var.name : "${substr(var.name, 0, 25)}-${substr(sha256(var.name), 0, 4)}"
  display_name = "Vertex AI model ${var.name}"
}

resource "google_storage_bucket_iam_member" "weights" {
  count = var.weights_bucket != null ? 1 : 0

  bucket = var.weights_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.this.email}"
}

# Dedicated endpoint: own DNS, no 1.5 MB body limit of the shared endpoint, needed for :invoke.
# No IAM binding here: callers need aiplatform.endpoints.predict on the project, so nothing becomes public.
resource "google_vertex_ai_endpoint" "this" {
  project = var.project_id
  # The endpoint ID must be numeric (max 10 digits); derive it from the name so it is stable.
  name                       = tostring(parseint(substr(sha256(var.name), 0, 8), 16))
  display_name               = var.name
  location                   = var.region
  region                     = var.region
  dedicated_endpoint_enabled = true

  lifecycle {
    precondition {
      condition     = var.invoke_routes != (var.predict_route != null)
      error_message = "Set exactly one of predict_route or invoke_routes = true."
    }
    precondition {
      condition     = (var.weights_dir == null) || (var.weights_bucket != null)
      error_message = "weights_dir needs weights_bucket."
    }
  }
}
