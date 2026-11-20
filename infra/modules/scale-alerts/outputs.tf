output "filters" {
  description = "Log filters of the ready and down policies. Deployment tests check them."
  value       = local.filters
}
