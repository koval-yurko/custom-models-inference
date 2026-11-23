# Phase 6 of docs/specs/2026-11-22-multi-platform-design.md: the code of infra/modules/vertex-model moved into this
# adapter. These blocks keep the resources of every deployment that called it as module.engine (no recreate of the
# endpoint or the service account).
moved {
  from = module.engine.google_service_account.this
  to   = google_service_account.this
}

moved {
  from = module.engine.google_storage_bucket_iam_member.weights
  to   = google_storage_bucket_iam_member.weights
}

moved {
  from = module.engine.google_vertex_ai_endpoint.this
  to   = google_vertex_ai_endpoint.this
}
