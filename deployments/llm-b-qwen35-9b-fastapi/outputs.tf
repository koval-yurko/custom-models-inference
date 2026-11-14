output "endpoint_id" {
  description = "Numeric endpoint ID."
  value       = module.model.endpoint_id
}

output "endpoint_dns" {
  description = "Dedicated endpoint DNS."
  value       = module.model.endpoint_dns
}

output "image" {
  description = "Image URL. image/cloudbuild.yaml must push this tag before scripts/vertex.py deploy."
  value       = local.image
}

# scripts/vertex.py reads this output.
output "vertex" {
  value = module.model.vertex
}

output "gateway_url" {
  description = "Public gateway URL. Calls need the x-api-key header (infra/core output api_key)."
  value       = "https://${google_api_gateway_gateway.this.default_hostname}"
}

# The test UI reads this output (scripts/ui-deploy.py -> models.json). Schema: .claude/skills/model-ui/SKILL.md.
output "ui" {
  description = "Tab of this model in the test UI."
  value = {
    id       = local.gateway_id
    title    = "LLM-B Qwen3.5 9B (FastAPI)"
    type     = "llm-routes"
    base_url = "https://${google_api_gateway_gateway.this.default_hostname}"
    model    = "qwen3.5-9b" # SERVED_MODEL_NAME in main.tf
    features = {
      cold_start = "vertex-429" # at 0 replicas Vertex AI returns 429 at once: the UI retries every 30 s
      max_tokens = 512
      routes     = keys(local.routes)
    }
  }
}
