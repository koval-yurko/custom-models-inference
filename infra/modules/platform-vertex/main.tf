# Vertex AI adapter of the model facade. It maps the platform-neutral spec to infra/modules/vertex-model and gives
# the common target output. The model upload and deploy stay in scripts/deploy.py (post_apply = "vertex").
locals {
  image_stock = try(var.spec.image.stock, null)
  # Docker Hub images without a namespace (python:3.13) are under library/ in the proxy repo.
  image = local.image_stock != null ? "${var.region}-docker.pkg.dev/${var.project_id}/dockerhub/${strcontains(local.image_stock, "/") ? "" : "library/"}${local.image_stock}" : "${var.region}-docker.pkg.dev/${var.project_id}/models/${var.spec.image.own}"

  gpu           = try(var.spec.gpu, null)
  accelerator   = { L4 = "NVIDIA_L4" }
  predict_route = try(var.options.predict_route, null)
  gcs_dir       = try(var.spec.weights.gcs_dir, null)
}

module "engine" {
  source = "../vertex-model"

  project_id = var.project_id
  region     = var.region
  name       = try(var.options.name, var.name)
  image      = local.image
  # Vertex AI sets AIP_STORAGE_URI from the model artifactUri.
  args = [for a in concat(var.spec.args, try(var.options.extra_args, [])) : replace(a, "{model}", "$(AIP_STORAGE_URI)")]
  env  = merge(try(var.spec.env, {}), { HF_HUB_OFFLINE = "1" }, try(var.options.env, {}))

  port          = try(var.spec.port, 8080)
  health_route  = var.spec.health_route
  predict_route = local.predict_route
  invoke_routes = local.predict_route == null

  machine_type          = try(var.options.machine_type, "g2-standard-8")
  accelerator_type      = local.gpu == null ? null : lookup(local.accelerator, local.gpu, null)
  accelerator_count     = 1
  shared_memory_size_mb = try(var.options.shared_memory_size_mb, null)
  deployment_timeout    = try(var.options.deployment_timeout, "1800s")
  max_replica_count     = try(var.spec.max_replicas, 1)
  idle_scaledown_period = "${try(var.spec.idle_seconds, 300)}s"

  weights_bucket = local.gcs_dir != null ? "${var.project_id}-models" : null
  weights_dir    = local.gcs_dir
}
