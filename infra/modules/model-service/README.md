# Module: model-service

Deploys 1 model as 1 private Cloud Run v2 service. The service scales to zero (min 0 instances).

It creates:

- a service account for the service,
- the Cloud Run service (GPU optional),
- `roles/run.invoker` for each member in `invokers`,
- `roles/storage.objectViewer` on `weights_bucket`, if you set one. The bucket is mounted read-only at `/models`.

## Inputs

| Variable | Default | Note |
|---|---|---|
| `project_id`, `region`, `name`, `image` | required | `name`: 6-49 chars, lowercase letters, digits, hyphens. SA ID = `name` if 30 chars or less, else 25 chars + `-` + 4 hash chars. |
| `invokers` | required | IAM members, for example `["user:me@example.com"]`. `allUsers` and `allAuthenticatedUsers` are rejected. |
| `args`, `env` | `[]`, `{}` | Container args and plain env vars. No secrets. |
| `port` | `8080` | Container port. Cloud Run sets `$PORT`. |
| `cpu`, `memory` | `"4"`, `"16Gi"` | Resource limits |
| `gpu_type` | `null` | `"nvidia-l4"` (min 4 CPU, 16Gi) or `"nvidia-rtx-pro-6000"` (min 20 CPU, 80Gi). GCP checks the minimums at apply time. |
| `concurrency` | `4` | Max requests per instance |
| `max_instances` | `1` | Min is always 0 |
| `timeout` | `"300s"` | Request timeout |
| `startup_probe_path` | `null` | HTTP probe path. `null` means a TCP probe. |
| `startup_failure_threshold` | `60` | With a 10 s period: 10 min |
| `weights_bucket` | `null` | Bucket to mount at `/models` |

Billing: a CPU service uses request-based billing (`cpu_idle = true`). A GPU service uses instance-based billing and has zonal redundancy off.

## Outputs

`url`, `service_name`, `service_account_email`.

## Example

```hcl
module "service" {
  source = "../../infra/modules/model-service"

  project_id         = var.project_id
  region             = var.region
  name               = "tts-a-kokoro-cpu"
  image              = "europe-west4-docker.pkg.dev/${var.project_id}/ghcr/remsky/kokoro-fastapi-cpu:v0.10.0"
  cpu                = "4"
  memory             = "8Gi"
  startup_probe_path = "/health"
  invokers           = ["user:me@example.com"]
}
```

## Tests

```sh
terraform init -backend=false
terraform test
```

The tests use a mock provider. They need no GCP credentials.
