# Vertex AI adapter of the model facade. One call = service account + objectViewer on the weights bucket + dedicated
# private endpoint, and the common target output. The model upload and deploy (scale to zero, Preview) stay in
# scripts/deploy.py (post_apply = "vertex"): the provider has no resource for them, so this module only builds their
# request bodies (output vertex).
locals {
  name        = try(var.options.name, var.name)
  image_stock = try(var.spec.image.stock, null)
  # Docker Hub images without a namespace (python:3.13) are under library/ in the proxy repo.
  # Vertex AI pulls only from Artifact Registry: stock images come through the infra/core dockerhub proxy repo.
  image = local.image_stock != null ? "${var.region}-docker.pkg.dev/${var.project_id}/dockerhub/${strcontains(local.image_stock, "/") ? "" : "library/"}${local.image_stock}" : "${var.region}-docker.pkg.dev/${var.project_id}/models/${var.spec.image.own}"

  gpu           = try(var.spec.gpu, null)
  accelerators  = { L4 = "NVIDIA_L4" }
  accelerator   = local.gpu == null ? null : lookup(local.accelerators, local.gpu, null)
  predict_route = try(var.options.predict_route, null)
  invoke_routes = local.predict_route == null
  gcs_dir       = try(var.spec.weights.gcs_dir, null)
  # Vertex AI sets AIP_STORAGE_URI from the model artifactUri.
  artifact_uri = local.gcs_dir != null ? "gs://${var.project_id}-models/${trim(local.gcs_dir, "/")}/" : null

  # Vertex AI expands $(AIP_STORAGE_URI) in the args.
  args = [for a in concat(var.spec.args, try(var.options.extra_args, [])) : replace(a, "{model}", "$(AIP_STORAGE_URI)")]
  # SETUP_PLATFORM: container contract of own images only (the setup record of STT-A).
  env = merge(try(var.spec.env, {}), { HF_HUB_OFFLINE = "1" }, try(var.spec.image.own, null) != null ? { SETUP_PLATFORM = "vertex" } : {}, try(var.options.env, {}))

  port                  = try(var.spec.port, 8080)
  shared_memory_size_mb = try(var.options.shared_memory_size_mb, null)
  max_replicas          = try(var.spec.max_replicas, 1)
  idle_seconds          = try(var.spec.idle_seconds, 300)

  # Request bodies for the Vertex AI REST API (v1beta1). scripts/platforms/vertex.py sends them.
  model_upload = {
    model = {
      displayName = local.name
      artifactUri = local.artifact_uri
      containerSpec = {
        imageUri           = local.image
        args               = local.args
        env                = [for k, v in local.env : { name = k, value = v }]
        ports              = [{ containerPort = local.port }]
        healthRoute        = var.spec.health_route
        predictRoute       = local.predict_route
        invokeRoutePrefix  = local.invoke_routes ? "/*" : null
        sharedMemorySizeMb = local.shared_memory_size_mb != null ? tostring(local.shared_memory_size_mb) : null
        deploymentTimeout  = try(var.options.deployment_timeout, "1800s")
      }
    }
  }

  deployed_model = {
    displayName    = local.name
    serviceAccount = google_service_account.this.email
    # v1beta1 has container logs off by default; scale-alerts needs them.
    enableContainerLogging = true
    dedicatedResources = {
      machineSpec = {
        machineType      = try(var.options.machine_type, "g2-standard-8")
        acceleratorType  = local.accelerator
        acceleratorCount = local.accelerator != null ? 1 : null
      }
      minReplicaCount     = 0
      maxReplicaCount     = local.max_replicas
      initialReplicaCount = 1
      scaleToZeroSpec = {
        minScaleupPeriod    = "300s"
        idleScaledownPeriod = "${local.idle_seconds}s"
      }
    }
  }
}

resource "google_service_account" "this" {
  project = var.project_id
  # SA IDs are 6-30 chars. Longer names get 25 chars + a hash, so names with the same prefix do not collide.
  account_id   = length(local.name) <= 30 ? local.name : "${substr(local.name, 0, 25)}-${substr(sha256(local.name), 0, 4)}"
  display_name = "Vertex AI model ${local.name}"
}

resource "google_storage_bucket_iam_member" "weights" {
  count = local.gcs_dir != null ? 1 : 0

  bucket = "${var.project_id}-models"
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.this.email}"
}

# Dedicated endpoint: own DNS, no 1.5 MB body limit of the shared endpoint, needed for :invoke.
data "google_project" "this" {
  project_id = var.project_id
}

locals {
  # dedicated_endpoint_dns is empty right after create. The DNS has a fixed format, so build it as a fallback.
  endpoint_dns = coalesce(google_vertex_ai_endpoint.this.dedicated_endpoint_dns, "${google_vertex_ai_endpoint.this.name}.${var.region}-${data.google_project.this.number}.prediction.vertexai.goog")
}

# No IAM binding here: callers need aiplatform.endpoints.predict on the project, so nothing becomes public.
resource "google_vertex_ai_endpoint" "this" {
  project = var.project_id
  # The endpoint ID must be numeric (max 10 digits); derive it from the name so it is stable.
  name                       = tostring(parseint(substr(sha256(local.name), 0, 8), 16))
  display_name               = local.name
  location                   = var.region
  region                     = var.region
  dedicated_endpoint_enabled = true

  lifecycle {
    precondition {
      condition     = can(regex("^[a-z][a-z0-9-]{4,47}[a-z0-9]$", local.name))
      error_message = "The Vertex AI name must be 6-49 chars, start with a lowercase letter, use only lowercase letters, digits and hyphens, and not end with a hyphen."
    }
    precondition {
      condition     = !anytrue([for k in keys(local.env) : startswith(k, "AIP_")])
      error_message = "env must not set AIP_ variables. Vertex AI sets them."
    }
    precondition {
      condition     = local.max_replicas >= 1
      error_message = "spec.max_replicas must be at least 1."
    }
    precondition {
      condition     = local.idle_seconds >= 300 && local.idle_seconds <= 28800
      error_message = "spec.idle_seconds must be between 300 and 28800 on Vertex AI."
    }
  }
}
