# Runpod adapter of the model facade. It maps the platform-neutral spec to 1 serverless template and 1 load
# balancing endpoint that scales to 0, and gives the common target output. post_apply is null: the endpoint is
# ready after apply. vLLM downloads the weights from Hugging Face at start (spec.weights.hf_repo at the revision).
locals {
  weights  = try(var.spec.weights, null)
  revision = try(local.weights.revision, null)
  port     = try(var.spec.port, 8080)
  name     = try(var.options.name, var.name)
  secret   = try(var.options.hf_token_secret, null)

  raw_args = concat(var.spec.args, try(var.options.extra_args, []), local.revision != null ? ["--revision=${local.revision}"] : [])
  args     = [for a in local.raw_args : local.weights != null ? replace(a, "{model}", local.weights.hf_repo) : a]
  bad_args = [for a in local.args : a if length(regexall("[\\s\"']", a)) > 0 || startswith(a, "{")]

  env = merge(
    try(var.spec.env, {}),
    { HF_HUB_OFFLINE = "0", PORT = tostring(local.port), PORT_HEALTH = tostring(local.port), HEALTH_CHECK_PATH = var.spec.health_route },
    local.secret != null ? { HF_TOKEN = "{{ RUNPOD_SECRET_${local.secret} }}" } : {},
    try(var.options.env, {}),
  )
}

resource "runpod_template" "this" {
  name       = local.name
  image      = try(var.spec.image.stock, null) != null ? var.spec.image.stock : "-" # own images fail in the precondition below
  args       = join(" ", local.args)                                                # Runpod takes 1 string
  env        = local.env
  ports      = ["${local.port}/http"]
  disk       = try(var.options.disk_gb, 60)
  serverless = true

  lifecycle {
    precondition {
      condition     = local.weights == null || local.revision != null
      error_message = "spec.weights.revision (a commit sha) is required on Runpod, so every platform loads the same weights."
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
    precondition {
      condition     = try(var.spec.image.stock, null) != null
      error_message = "Runpod in phase 3: stock images only. Own images come in phase 6."
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
  workers_min    = 0 # scale to zero
  workers_max    = try(var.spec.max_replicas, 1)
  idle_timeout   = try(var.spec.idle_seconds, 300)
  flashboot      = "FLASHBOOT"

  lifecycle {
    # Runpod copies the template into the endpoint only at create (template_id). A template change (image,
    # args, env, ports) must replace the endpoint. The URL changes; the proxy gets the new one in the same apply.
    replace_triggered_by = [runpod_template.this]
  }
}
