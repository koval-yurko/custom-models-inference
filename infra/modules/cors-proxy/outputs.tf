output "url" {
  description = "Proxy URL. Use it as the x-google-backend address of the gateway."
  value       = module.service.url
}

output "service_name" {
  description = "Cloud Run service name."
  value       = module.service.service_name
}

output "service_account_email" {
  description = "Service account of the proxy (aiplatform.user when a target uses auth = google)."
  value       = module.service.service_account_email
}

output "env" {
  description = "Plain env vars of the proxy (TARGETS JSON, DEFAULT, TIMEOUT). For tests."
  value       = local.env
}
