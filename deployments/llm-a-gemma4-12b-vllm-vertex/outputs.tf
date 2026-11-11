output "endpoint_id" {
  description = "Numeric endpoint ID."
  value       = module.model.endpoint_id
}

output "endpoint_dns" {
  description = "Dedicated endpoint DNS."
  value       = module.model.endpoint_dns
}

# vertex.sh reads this output.
output "vertex" {
  value = module.model.vertex
}

output "gateway_url" {
  description = "Public gateway URL. It changes when scripts/gateway-streaming.py makes the streaming gateway (the script refreshes the state)."
  value       = "https://${google_api_gateway_gateway.this.default_hostname}"
}

output "gateway_id" {
  description = "Gateway ID (for scripts/gateway-streaming.py)."
  value       = google_api_gateway_gateway.this.gateway_id
}

output "gateway_region" {
  description = "Gateway region (for scripts/gateway-streaming.py)."
  value       = google_api_gateway_gateway.this.region
}

output "api_config" {
  description = "Full API config name (for scripts/gateway-streaming.py)."
  value       = google_api_gateway_api_config.this.id
}

# The test UI reads this output (scripts/ui-deploy.py -> models.json). Schema: .claude/skills/model-ui/SKILL.md.
output "ui" {
  description = "Tab of this model in the test UI."
  value = {
    id       = local.gateway_id
    title    = "LLM-A Gemma 4 12B"
    type     = "llm"
    base_url = "https://${google_api_gateway_gateway.this.default_hostname}"
    model    = "gemma-4-12b" # --served-model-name in main.tf
    features = {
      stream      = true # SSE: needs scripts/gateway-streaming.py
      max_tokens  = 1024
      cold_start  = "vertex-429" # at 0 replicas Vertex AI returns 429 at once: the UI retries every 30 s
      max_context = 32768        # --max-model-len in main.tf
    }
  }
}
