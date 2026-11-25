# Modal adapter of the model facade. Modal has no Terraform provider, so this module makes no resource. It maps the
# platform-neutral spec to the input of scripts/platforms/modal.py (output modal), which runs `modal deploy` after
# apply with the shared app file scripts/platforms/modal_app.py. Only own images: the app file removes the image
# ENTRYPOINT (Modal must start its own runtime) and starts options.command itself.
# Weights: on the Modal Volume options.volume at /models/<spec.weights.gcs_dir>. modal.py fills it once from Hugging
# Face (options.hf_repos). A Volume is not pinned to a region, so the GPU can start anywhere.
locals {
  name    = try(var.options.name, var.name)
  own     = try(var.spec.image.own, null)
  port    = try(var.spec.port, 8080)
  gcs_dir = try(var.spec.weights.gcs_dir, null)
  model   = local.gcs_dir != null ? "/models/${local.gcs_dir}" : null

  env = merge(
    try(var.spec.env, {}),
    { PORT = tostring(local.port), HF_HUB_OFFLINE = "1", SETUP_PLATFORM = "modal" }, # the container contract
    # A segfault prints the Python stack of each thread (a crash in a Modal container leaves little else in the log).
    { PYTHONFAULTHANDLER = "1" },
    local.model != null ? { MODEL = local.model } : {},
    try(var.options.env, {}),
  )
}
