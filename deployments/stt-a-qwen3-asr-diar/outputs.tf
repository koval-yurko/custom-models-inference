output "endpoint_id" {
  description = "Numeric Vertex AI endpoint ID."
  value       = module.model.vertex_endpoint_id
}

output "endpoint_dns" {
  description = "Dedicated Vertex AI endpoint DNS."
  value       = module.model.vertex_endpoint_dns
}

output "image" {
  description = "Image name and tag in the models repo. services/speech_engine/cloudbuild.yaml must push this tag before apply and deploy."
  value       = "stt-a-qwen3-asr-diar:${var.image_tag}"
}

# scripts/platforms/vertex.py reads this output.
output "vertex" {
  value = module.model.vertex
}

# scripts/platforms/modal.py reads this output.
output "modal" {
  value = module.model.modal
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

# scripts/runpod-weights.py reads this output.
output "runpod_volumes" {
  description = "Runpod network volumes of the weights: { dir, volumes = [{ id, data_center }] }."
  value       = module.model.runpod_volumes
}

output "weights_gcs" {
  description = "Source of the weights copy to the Runpod volume (scripts/runpod-weights.py)."
  value       = "gs://${var.project_id}-models/${local.model_dir}/"
}

output "gateway_url" {
  description = "Public gateway URL. Calls need the x-api-key header (infra/core output api_key)."
  value       = module.model.gateway_url
}

output "gateway_id" {
  description = "Gateway ID."
  value       = module.model.gateway_id
}

output "gateway_region" {
  description = "Gateway region."
  value       = module.model.gateway_region
}

output "api_config" {
  description = "Full API config name."
  value       = module.model.api_config
}

output "gateway_address" {
  description = "State address of the gateway."
  value       = "module.model.${module.model.gateway_address}"
}

output "stt_api_url" {
  description = "STT API service URL (private). The gateway paths /v1beta/uploads, /v1beta/files... and /v1beta/scores call it."
  value       = module.stt_api.url
}

# The test UI reads this output (scripts/ui-deploy.py -> models.json). Schema: .claude/skills/model-ui/SKILL.md.
output "ui" {
  description = "Tab of this model in the test UI."
  value = {
    id       = module.model.gateway_id
    title    = "STT-A Qwen3 ASR + speakers"
    type     = "stt"
    base_url = module.model.ui_platforms[0].base_url # the default platform (the first in local.platforms)
    model    = "qwen3-asr-diar"
    features = {
      max_mb = 20 # larger files go through /v1beta/uploads
    }
    # 1 entry per platform: { id, label, base_url, cold_start }. All use retry-429: Vertex AI answers 429 at 0
    # replicas; the proxy answers 429 when Runpod or Modal sends no answer in 280 s (a container is starting).
    platforms = module.model.ui_platforms
  }
}
