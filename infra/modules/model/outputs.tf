output "serving_platforms" {
  description = "Platforms that serve calls (proxy targets and gateway paths), in the order of platforms."
  value       = tolist(local.serving)
}

output "platforms" {
  description = "Platform ids in order. The first one is the default."
  value       = var.platforms
}

output "targets" {
  description = "Platform id -> adapter target (id, label, url, append_path, auth, cold_start, deadline, post_apply). scripts/deploy.py reads it."
  value       = local.targets
}

output "ui_platforms" {
  description = "Platforms for the ui output of the deployment (scripts/ui-deploy.py -> models.json), in the order of platforms."
  value = [for p in local.serving : {
    id         = p
    label      = local.targets[p].label
    base_url   = "${module.gateway.gateway_url}/${p}"
    cold_start = local.targets[p].cold_start
  }]
}

output "gateway_url" {
  description = "Public gateway URL."
  value       = module.gateway.gateway_url
}

output "gateway_id" {
  description = "Gateway ID."
  value       = module.gateway.gateway_id
}

output "gateway_region" {
  description = "Gateway region."
  value       = module.gateway.gateway_region
}

output "api_config" {
  description = "Full API config name."
  value       = module.gateway.api_config
}

output "gateway_address" {
  description = "State address of the gateway in this module. The root adds \"module.<name>.\"."
  value       = "module.gateway.${module.gateway.address}"
}

output "openapi" {
  description = "The OpenAPI document of the gateway (for tests)."
  value       = module.gateway.openapi
}

output "vertex" {
  description = "Input for scripts/platforms/vertex.py. null without vertex."
  value       = try(module.vertex[0].vertex, null)
}

output "modal" {
  description = "Input for scripts/platforms/modal.py. null without modal."
  value       = try(module.modal[0].modal, null)
}

output "vertex_endpoint_id" {
  description = "Vertex AI endpoint ID. null without vertex."
  value       = try(module.vertex[0].endpoint_id, null)
}

output "vertex_endpoint_dns" {
  description = "Vertex AI endpoint DNS. null without vertex."
  value       = try(module.vertex[0].endpoint_dns, null)
}

output "runpod_args" {
  description = "The args string of the Runpod template (for tests). null without runpod."
  value       = try(module.runpod[0].args, null)
}

output "scale_watch_ids" {
  description = "Platform id to the ID that the infra/core job scale-watch prints (Runpod endpoint). Only platforms without GCP logs. For the Slack alerts in alerts.tf."
  value = merge(
    contains(local.serving, "runpod") ? { runpod = module.runpod[0].endpoint_id } : {},
  )
}

output "proxy_url" {
  description = "URL of the CORS proxy (private). The STT-A stt_api service calls <proxy_url>/<platform>/v1beta/interactions."
  value       = module.cors_proxy.url
}

output "vertex_service_account_email" {
  description = "Service account of the Vertex AI model. null without vertex."
  value       = try(module.vertex[0].service_account_email, null)
}

output "runpod_volumes" {
  description = "Runpod network volumes of the weights { dir, volumes = [{ id, data_center }] } (scripts/runpod-weights.py). null without them."
  value       = try(module.runpod[0].volumes, null)
}


output "gateway_service_account_email" {
  description = "Service account of the API Gateway. A backend outside the proxy (STT-A stt_api) gives it run.invoker."
  value       = module.gateway.service_account_email
}

output "runpod_env" {
  description = "The env of the Runpod template (for tests). null without runpod."
  value       = try(module.runpod[0].env, null)
}

output "proxy_extra_invoker_count" {
  description = "Number of proxy_invokers that got run.invoker on the proxy (for tests)."
  value       = module.cors_proxy.extra_invoker_count
}
