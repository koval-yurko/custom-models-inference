# Private Cloud Run service between an API Gateway and a Vertex AI endpoint. Vertex AI sends no CORS
# headers (not on OPTIONS, not on 200, 429 or 5xx), and API Gateway cannot add them. The proxy adds
# them to every answer and forwards GET and POST to the target of the platform (cors_proxy.py). The first path
# segment picks the target; other paths go to default_platform. The gateway SA may call it. The proxy SA may call
# Vertex AI (only when a target uses auth = google) and reads the provider keys of secret_env.
locals {
  env = {
    TARGETS = jsonencode(var.targets)
    DEFAULT = var.default_platform
    TIMEOUT = trimsuffix(var.timeout, "s")
  }
}

module "service" {
  source = "../model-service"

  project_id = var.project_id
  region     = var.region
  name       = var.name
  image      = var.image
  command    = ["python3"]
  args       = ["-u", "-c", file("${path.module}/cors_proxy.py")]
  env        = local.env
  secret_env = var.secret_env

  cpu           = "1"
  memory        = "256Mi"
  concurrency   = 80
  max_instances = 2
  timeout       = var.timeout
  invokers      = [] # the gateway SA is unknown at plan time on a first apply, so no for_each
}

resource "google_cloud_run_v2_service_iam_member" "gateway_invoker" {
  project  = var.project_id
  location = var.region
  name     = module.service.service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.gateway_service_account_email}"
}

# The provider has no IAM resource for 1 Vertex AI endpoint, so the role is on the project.
# The member is the proxy SA of this module call only, so destroy removes only this binding.
resource "google_project_iam_member" "predict" {
  count = anytrue([for t in values(var.targets) : t.auth == "google"]) ? 1 : 0

  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${module.service.service_account_email}"
}

moved {
  from = google_project_iam_member.predict
  to   = google_project_iam_member.predict[0]
}
