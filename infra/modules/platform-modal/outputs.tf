output "target" {
  description = "The common adapter output. The model facade merges it into targets."
  value = {
    id          = "modal"
    label       = "Modal"
    url         = "https://${var.options.workspace}--${local.name}.modal.run" # the label of the web server is the app name
    append_path = true
    auth        = "modal"     # the proxy sends MODAL_API_KEY (a Modal proxy token)
    cold_start  = "retry-429" # the request waits; the proxy follows the 303 after 150 s and answers 429 after 280 s
    deadline    = 300
    post_apply  = "modal" # scripts/platforms/modal.py runs modal deploy
  }

  precondition {
    condition     = local.own != null && length(local.name) <= 63 && can(var.options.workspace) && length(try(var.options.command, [])) > 0
    error_message = "platform-modal needs spec.image.own, options.workspace, options.command, and a name of 63 characters or less."
  }
}

output "modal" {
  description = "Input for scripts/platforms/modal.py and scripts/platforms/modal_app.py."
  value = {
    app            = local.name
    image          = "${var.region}-docker.pkg.dev/${var.project_id}/models/${coalesce(local.own, "-")}"
    command        = try(var.options.command, [])
    workdir        = try(var.options.workdir, "/")
    port           = local.port
    health_route   = var.spec.health_route
    gpus           = try(var.options.gpus, ["L4", "A10"]) # a fallback list in this order
    cpu            = try(var.options.cpu, 4)
    memory_mb      = try(var.options.memory_mb, 32768)
    max_containers = try(var.spec.max_replicas, 1)
    idle_seconds   = min(try(var.spec.idle_seconds, 300), 1200) # Modal scaledown_window: 2 s to 20 min
    timeout        = try(var.options.timeout, 600)
    volume         = try(var.options.volume, "${local.name}-weights")
    weights_dir    = local.gcs_dir
    hf_repos       = try(var.options.hf_repos, {})
    env            = local.env
  }
}
