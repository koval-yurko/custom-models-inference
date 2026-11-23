# Phase 1 of docs/specs/2026-11-22-multi-platform-design.md: LLM-A moved from vertex-model, gateway.tf and
# cors_proxy.tf to infra/modules/model. These blocks keep every resource (no recreate of the endpoint, the gateway
# or a service account). The old module.model (vertex-model) becomes module.model (the facade), so its resources
# move one by one: a module cannot move into its own child address.
moved {
  from = module.model.google_service_account.this
  to   = module.model.module.vertex[0].module.engine.google_service_account.this
}

moved {
  from = module.model.google_storage_bucket_iam_member.weights[0]
  to   = module.model.module.vertex[0].module.engine.google_storage_bucket_iam_member.weights[0]
}

moved {
  from = module.model.google_vertex_ai_endpoint.this
  to   = module.model.module.vertex[0].module.engine.google_vertex_ai_endpoint.this
}

moved {
  from = module.cors_proxy
  to   = module.model.module.cors_proxy
}

moved {
  from = google_service_account.gateway
  to   = module.model.module.gateway.google_service_account.this
}

moved {
  from = google_api_gateway_api_config.this
  to   = module.model.module.gateway.google_api_gateway_api_config.this
}

moved {
  from = google_api_gateway_gateway.this
  to   = module.model.module.gateway.google_api_gateway_gateway.this
}

moved {
  from = module.scale_alerts
  to   = module.scale_alerts[0]
}
