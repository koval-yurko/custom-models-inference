output "target" {
  description = "The common adapter output. The model facade merges it into targets. null with options.serve = false."
  value = local.serve ? {
    id          = "runpod"
    label       = "Runpod"
    url         = runpod_serverless_endpoint.this[0].request_urls.base
    append_path = true        # the proxy appends the route to the base URL
    auth        = "runpod"    # the proxy sends RUNPOD_API_KEY
    cold_start  = "retry-429" # the proxy maps "no workers available" to 429 (cold_answer)
    deadline    = 300         # a load balancing request may run 5.5 min at most
    post_apply  = null
  } : null
}

output "endpoint_id" {
  description = "Runpod endpoint ID. null with options.serve = false."
  value       = try(runpod_serverless_endpoint.this[0].id, null)
}

output "args" {
  description = "The args string of the template (for tests)."
  value       = runpod_template.this.args
}

output "volumes" {
  description = "The network volumes of the weights: { dir, volumes = [{ id, data_center }] } (scripts/runpod-weights.py fills each). null without options.volume."
  value = local.volume != null ? {
    dir     = local.gcs_dir
    volumes = [for dc in sort(tolist(local.volume_dcs)) : { id = runpod_network_volume.this[dc].id, data_center = dc }]
  } : null
}

output "env" {
  description = "The env of the template (for tests)."
  value       = local.env
}

