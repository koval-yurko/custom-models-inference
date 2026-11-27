output "endpoint_id" {
  description = "Numeric endpoint ID."
  value       = module.model.vertex_endpoint_id
}

output "endpoint_dns" {
  description = "Dedicated endpoint DNS."
  value       = module.model.vertex_endpoint_dns
}

# scripts/platforms/vertex.py reads this output.
output "vertex" {
  value = module.model.vertex
}

# scripts/deploy.py reads these outputs.
output "platforms" {
  description = "Platform ids in order. The first one is the default."
  value       = module.model.serving_platforms # serve = false platforms are left out
}

output "targets" {
  description = "Platform id -> target (url, auth, post_apply, ...)."
  value       = module.model.targets
}

output "gateway_url" {
  description = "Public gateway URL. It changes when scripts/gateway-streaming.py makes the streaming gateway (the script refreshes the state)."
  value       = module.model.gateway_url
}

output "gateway_id" {
  description = "Gateway ID (for scripts/gateway-streaming.py)."
  value       = module.model.gateway_id
}

output "gateway_region" {
  description = "Gateway region (for scripts/gateway-streaming.py)."
  value       = module.model.gateway_region
}

output "api_config" {
  description = "Full API config name (for scripts/gateway-streaming.py)."
  value       = module.model.api_config
}

output "gateway_address" {
  description = "State address of the gateway (for scripts/gateway-streaming.py)."
  value       = "module.model.${module.model.gateway_address}"
}

# The test UI reads this output (scripts/ui-deploy.py -> models.json). Schema: .claude/skills/model-ui/SKILL.md.
output "ui" {
  description = "Tab of this model in the test UI."
  value = {
    id       = module.model.gateway_id
    title    = "LLM-A Gemma 4 12B"
    type     = "llm"
    base_url = module.model.ui_platforms[0].base_url # the default platform (the first in local.platforms)
    model    = "gemma-4-12b"                         # --served-model-name in main.tf (spec.args)
    features = {
      stream      = true # SSE: needs scripts/gateway-streaming.py
      max_tokens  = 1024
      max_context = 32768 # --max-model-len in main.tf
    }
    # 1 entry per platform: { id, label, base_url, cold_start }. cold_start is per platform (retry-429: the UI retries a real 429 every 30 s).
    platforms = module.model.ui_platforms
  }
}
