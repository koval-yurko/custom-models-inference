output "target" {
  description = "The common adapter output. The model facade merges it into targets."
  value = {
    id          = "runpod"
    label       = "Runpod"
    url         = runpod_serverless_endpoint.this.request_urls.base
    append_path = true        # the proxy appends the route to the base URL
    auth        = "runpod"    # the proxy sends RUNPOD_API_KEY
    cold_start  = "retry-429" # the proxy maps "no workers available" to 429 (cold_answer)
    deadline    = 300         # a load balancing request may run 5.5 min at most
    post_apply  = null
  }
}

output "endpoint_id" {
  description = "Runpod endpoint ID."
  value       = runpod_serverless_endpoint.this.id
}

output "args" {
  description = "The args string of the template (for tests)."
  value       = runpod_template.this.args
}
