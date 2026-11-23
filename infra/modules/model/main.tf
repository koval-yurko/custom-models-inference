# One model spec on a list of platforms. One adapter per platform (only vertex in phase 1), one CORS proxy and
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

locals {
  # Later phases add one entry per adapter.
  all_targets = merge(
    contains(var.platforms, "vertex") ? { vertex = module.vertex[0].target } : {},
  )
  targets = { for p in var.platforms : p => local.all_targets[p] }
}

module "cors_proxy" {
  source = "../cors-proxy"

  project_id                    = var.project_id
  region                        = var.region
  name                          = "${var.gateway_id}-proxy"
  image                         = "${var.region}-docker.pkg.dev/${var.project_id}/dockerhub/library/python:3.13.9-slim"
  targets                       = { for p, t in local.targets : p => { url = t.url, append_path = t.append_path, auth = t.auth } }
  default_platform              = var.platforms[0]
  timeout                       = "${max([for t in values(local.targets) : t.deadline]...)}s"
  gateway_service_account_email = module.gateway.service_account_email
}

module "gateway" {
  source = "../gateway"

  project_id  = var.project_id
  region      = var.gateway_region
  gateway_id  = var.gateway_id
  backend_url = module.cors_proxy.url
  platforms   = var.platforms
  routes      = var.spec.routes
  deadlines   = { for p, t in local.targets : p => t.deadline }
}
