output "url" {
  description = "Proxy URL. Use it as the x-google-backend address of the gateway."
  value       = module.service.url
}

output "service_name" {
  description = "Cloud Run service name."
  value       = module.service.service_name
}

output "service_account_email" {
  description = "Service account of the proxy (it has aiplatform.user)."
  value       = module.service.service_account_email
}
