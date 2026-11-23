# Runpod adapter of the model facade. It maps the platform-neutral spec to 1 serverless template and 1 load
# balancing endpoint that scales to 0, and gives the common target output. post_apply is null: the endpoint is
# ready after apply. Weights: without options.volume, vLLM downloads them from Hugging Face at start
# (spec.weights.hf_repo at the revision). With options.volume, they are on a Runpod network volume at
# /runpod-volume/<spec.weights.gcs_dir> (scripts/runpod-weights.py copies them there from the GCS weights bucket).
# Own images (spec.image.own) come from the Artifact Registry repo models with the infra/core registry credential.
locals {
  weights  = try(var.spec.weights, null)
  revision = try(local.weights.revision, null)
  gcs_dir  = try(local.weights.gcs_dir, null)
  volume   = try(var.options.volume, null)
  # 1 volume per data center. A worker starts only in a data center with a volume, so more data centers give more
  # GPUs to choose from. Runpod mounts the volume of the worker's data center (1 volume per data center).
  volume_dcs = local.volume != null ? toset(local.volume.data_centers) : toset([])
  port       = try(var.spec.port, 8080)
  name       = try(var.options.name, var.name)
  secret     = try(var.options.hf_token_secret, null)
  stock      = try(var.spec.image.stock, null)
  own        = try(var.spec.image.own, null)
  image      = local.own != null ? "${var.region}-docker.pkg.dev/${var.project_id}/models/${local.own}" : local.stock

  # The weights path that {model} and env MODEL get.
  model_path = local.volume != null ? "/runpod-volume/${coalesce(local.gcs_dir, "-")}" : try(local.weights.hf_repo, null)

  raw_args = concat(var.spec.args, try(var.options.extra_args, []), local.volume == null && local.revision != null ? ["--revision=${local.revision}"] : [])
  args     = [for a in local.raw_args : local.model_path != null ? replace(a, "{model}", local.model_path) : a]
  bad_args = [for a in local.args : a if length(regexall("[\\s\"']", a)) > 0 || startswith(a, "{")]

  env = merge(
    try(var.spec.env, {}),
    {
      HF_HUB_OFFLINE    = local.volume != null ? "1" : "0"
      PORT              = tostring(local.port)
      PORT_HEALTH       = tostring(local.port)
      HEALTH_CHECK_PATH = var.spec.health_route
    },
    # Container contract of own images (docs/specs/2026-11-22-multi-platform-design.md). Not for stock images:
    # a new env value changes the template, and a template change replaces the endpoint.
    local.own != null ? { SETUP_PLATFORM = "runpod" } : {},
    local.volume != null ? { MODEL = local.model_path } : {},
    local.secret != null ? { HF_TOKEN = "{{ RUNPOD_SECRET_${local.secret} }}" } : {},
    try(var.options.env, {}),
  )

  registry_name = try(var.options.registry, "gcp-models")
  registry_id   = local.own != null ? module.registry[0].id : null
}

# The registry credential that infra/core makes (runpod_registry.tf). Found by name, so this root needs no core state.
module "registry" {
  source = "./registry"
  count  = local.own != null ? 1 : 0

  name = local.registry_name
}

resource "runpod_network_volume" "this" {
  for_each = local.volume_dcs

  name        = local.name
  data_center = each.key
  size        = try(local.volume.size_gb, 20) # can grow, never shrink
  type        = try(local.volume.type, "STANDARD")
}

resource "runpod_template" "this" {
  name       = local.name
  image      = local.image
  registry   = local.registry_id
  args       = join(" ", local.args) # Runpod takes 1 string
  env        = local.env
  ports      = ["${local.port}/http"]
  disk       = try(var.options.disk_gb, 60)
  serverless = true

  lifecycle {
    precondition {
      condition     = local.weights == null || local.volume != null || local.revision != null
      error_message = "spec.weights.revision (a commit sha) is required on Runpod without a volume, so every platform loads the same weights."
    }
    precondition {
      condition     = local.volume == null || length(local.volume_dcs) > 0
      error_message = "options.volume.data_centers must list at least 1 data center (with the S3 API, for scripts/runpod-weights.py)."
    }
    precondition {
      condition     = local.volume == null || local.gcs_dir != null
      error_message = "options.volume needs spec.weights.gcs_dir: the weights folder on the volume (the same as in the GCS weights bucket)."
    }
    precondition {
      condition     = local.own == null || local.registry_id != null
      error_message = "No Runpod registry credential named \"${local.registry_name}\" for the own image. Apply infra/core first (runpod_registry.tf)."
    }
    precondition {
      # Runpod splits the 1 args string on white space, and reads a string that starts with { as JSON.
      condition     = length(local.bad_args) == 0
      error_message = "Runpod args are 1 string: an arg must not contain a space, a tab, a newline or a quote, and must not start with { (${join(", ", local.bad_args)})."
    }
    precondition {
      condition     = local.weights != null || !anytrue([for a in var.spec.args : strcontains(a, "{model}")])
      error_message = "spec.args uses {model}, but spec.weights is not set: Runpod has no weights path to put there."
    }
    precondition {
      condition     = try(var.spec.gpu, null) != null
      error_message = "Runpod in phase 3: GPU models only (spec.gpu)."
    }
  }
}

resource "runpod_serverless_endpoint" "this" {
  name           = local.name
  template_id    = runpod_template.this.id
  endpoint_type  = "LOAD_BALANCER"
  scaling_type   = "REQUEST_COUNT"
  scaling_value  = try(var.options.scaling_value, 4)
  gpu_pools      = try(var.options.gpu_pools, ["AMPERE_24"]) # any cloud type, no data center pin
  excluded_types = try(var.options.excluded_types, [])
  gpu_count      = 1
  # The volumes tie the workers to their data centers.
  # Sorted by ID: Runpod returns them in that order, and another order gives "inconsistent result after apply".
  network_volumes = local.volume != null ? sort([for v in values(runpod_network_volume.this) : v.id]) : null
  data_center_ids = local.volume != null ? sort(tolist(local.volume_dcs)) : null
  workers_min     = 0 # scale to zero
  workers_max     = try(var.spec.max_replicas, 1)
  idle_timeout    = try(var.spec.idle_seconds, 300)
  flashboot       = "FLASHBOOT"

  lifecycle {
    # Runpod copies the template into the endpoint only at create (template_id). A template change (image,
    # args, env, ports) must replace the endpoint. The URL changes; the proxy gets the new one in the same apply.
    replace_triggered_by = [runpod_template.this]
  }
}
