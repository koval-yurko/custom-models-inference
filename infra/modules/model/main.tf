# One model spec on a list of platforms. One adapter per platform (vertex, runpod, modal), one CORS proxy and
# one API Gateway. The gateway, the proxy and the scripts read only local.targets, never the platform id.
module "vertex" {
  source = "../platform-vertex"
  count  = contains(var.platforms, "vertex") ? 1 : 0

  project_id = var.project_id
  region     = var.region
  name       = var.name
  spec       = var.spec
  options    = try(var.platform_options.vertex, {})
}

module "runpod" {
  source = "../platform-runpod"
  count  = contains(var.platforms, "runpod") ? 1 : 0

  project_id = var.project_id
  region     = var.region
  name       = var.name
  spec       = var.spec
  options    = try(var.platform_options.runpod, {})
}

module "modal" {
  source = "../platform-modal"
  count  = contains(var.platforms, "modal") ? 1 : 0

  project_id = var.project_id
  region     = var.region
  name       = var.name
  spec       = var.spec
  options    = try(var.platform_options.modal, {})
}

locals {
  # One entry per adapter.
  all_targets = merge(
    contains(var.platforms, "vertex") ? { vertex = module.vertex[0].target } : {},
    contains(var.platforms, "runpod") ? { runpod = module.runpod[0].target } : {},
    contains(var.platforms, "modal") ? { modal = module.modal[0].target } : {},
  )
  # Platforms that serve calls: platform_options.<id>.serve = false keeps the resources of a platform (for example the
  # Runpod volumes with the weights) but gives it no target, so the proxy and the gateway leave it out.
  serving = [for p in var.platforms : p if try(var.platform_options[p].serve, true) && local.all_targets[p] != null]
  targets = { for p in local.serving : p => local.all_targets[p] }
}

module "cors_proxy" {
  source = "../cors-proxy"

  project_id       = var.project_id
  region           = var.region
  name             = "${var.gateway_id}-proxy"
  image            = "${var.region}-docker.pkg.dev/${var.project_id}/dockerhub/library/python:3.13.9-slim"
  targets          = { for p, t in local.targets : p => { url = t.url, append_path = t.append_path, auth = t.auth } }
  default_platform = local.serving[0]
  # 1 provider key per non-google auth: env RUNPOD_API_KEY (MODAL_API_KEY) from the infra/core secret runpod-api-key (modal-api-key).
  secret_env                    = { for a in distinct([for t in values(local.targets) : t.auth if t.auth != "google"]) : "${upper(a)}_API_KEY" => "${a}-api-key" }
  timeout                       = "${max([for t in values(local.targets) : t.deadline]...)}s"
  gateway_service_account_email = module.gateway.service_account_email
  extra_invokers                = var.proxy_invokers
}

module "gateway" {
  source = "../gateway"

  project_id  = var.project_id
  region      = var.gateway_region
  gateway_id  = var.gateway_id
  backend_url = module.cors_proxy.url
  platforms   = local.serving
  routes      = var.spec.routes
  deadlines   = { for p, t in local.targets : p => t.deadline }
  extra_paths = var.extra_paths
}
