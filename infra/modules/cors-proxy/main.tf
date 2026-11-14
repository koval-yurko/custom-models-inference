# Private Cloud Run service between an API Gateway and a Vertex AI endpoint. Vertex AI sends no CORS
# headers (not on OPTIONS, not on 200, 429 or 5xx), and API Gateway cannot add them. The proxy adds
# them to every answer and forwards the POST to rawPredict (or :invoke + path) with its own access token (cors_proxy.py).
# The gateway SA may call it. The proxy SA may call Vertex AI.
module "service" {
  source = "../model-service"

  project_id = var.project_id
  region     = var.region
  name       = var.name
  image      = var.image
  command    = ["python3"]
  args       = ["-u", "-c", file("${path.module}/cors_proxy.py")]
  env        = { TARGET = var.target }

  cpu           = "1"
  memory        = "256Mi"
  concurrency   = 80
  max_instances = 2
  timeout       = "300s"
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
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${module.service.service_account_email}"
}
