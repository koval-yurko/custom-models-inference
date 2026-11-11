output "url" {
  description = "Service URL."
  value       = module.service.url
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
    title    = "TTS-A Kokoro"
    type     = "tts"
    base_url = "https://${google_api_gateway_gateway.this.default_hostname}"
    model    = "kokoro"
    features = {
      stream        = true # gateway streaming: needs scripts/gateway-streaming.py
      voices        = true # GET /v1/audio/voices
      default_voice = "af_heart"
      formats       = ["mp3", "wav", "opus", "flac", "pcm"]
      sample_rate   = 24000 # of the "pcm" format: 16-bit mono
    }
  }
}
