output "gateway_url" {
  description = "Public gateway URL. It changes when scripts/gateway-streaming.py makes the streaming gateway."
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

output "service_account_email" {
  description = "Gateway SA. Give it run.invoker on the backends."
  value       = google_service_account.this.email
}

output "address" {
  description = "State address of the gateway in this module. The caller adds its module path (for scripts/gateway-streaming.py)."
  value       = "google_api_gateway_gateway.this"
}

output "openapi" {
  description = "The OpenAPI document (for tests)."
  value       = local.openapi
}
