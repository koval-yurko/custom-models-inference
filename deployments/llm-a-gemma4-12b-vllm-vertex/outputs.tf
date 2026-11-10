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
