# Research: Serverless inference of custom models on GCP

Date: 2026-11-08. Card: "Project setup".

## Goal

- Deploy custom LLM, STT (speech to text) and TTS (text to speech) models on GCP.
- Pay only when a model runs (scale to zero).
- Use a custom container when a model needs Python code for inference.
- Manage all infrastructure with Terraform.
- Make it easy to add and remove models for experiments.

## Options on GCP

| Criterion | Cloud Run + GPU | Vertex AI endpoint | GKE Autopilot + GPU |
|---|---|---|---|
| Scale to zero | Yes, GA. Default `min_instance_count = 0`. | Preview only. Defaults: 1 h idle before scale down. First request after zero gets HTTP 429 and is dropped. | Pods can scale to 0, but you need KEDA or a similar add-on. Cluster fee applies. |
| GPUs | 1 per instance: L4 (24 GB) or RTX PRO 6000 Blackwell (96 GB). | Many types (L4, A100, H100, TPU). | Many types. |
| Billing | Per second while an instance runs (instance-based billing). | Per node-hour while a replica runs. | Per pod resources plus cluster management fee. |
| Cold start | Container start in seconds. Model load is the main cost (30 s to minutes). | Minutes. | Minutes (node provision + image pull). |
| Custom container | Any OCI image. | Any image that meets the Vertex serving contract (health and predict routes). | Any image. |
| Terraform | `google_cloud_run_v2_service`. Simple. | `google_vertex_ai_endpoint` + model upload. Deploy step often needs `gcloud`. | Cluster + Kubernetes manifests. The most work. |
| Operations | Lowest. | Medium. | Highest. |

## Recommendation

Use **Cloud Run services with GPU** as the main platform.

1. It is the only option with GA scale to zero and per-second billing.
2. It runs any container, so custom Python code is simple.
3. One Terraform resource deploys one model. This is good for experiments.
4. Use Vertex AI or GKE only when a model needs more than 1 GPU or more than 96 GB of VRAM.

Limits to know:

- 1 GPU per instance. Models larger than about 70B (quantized) do not fit.
- L4 needs at least 4 CPU and 16 GiB memory. RTX PRO 6000 needs at least 20 CPU and 80 GiB memory.
- GPU instances need instance-based billing (`cpu_idle = false`).
- GPU zonal redundancy is on by default and costs more. Turn it off for experiments (`gpu_zonal_redundancy_disabled = true`).
- GPU quota is per region. A new project gets a small L4 quota (about 3). Ask for more if necessary.
- GPU regions are limited. Check the docs before you select a region. `us-central1` and `europe-west4` have both GPU types.

Approximate GPU prices (third-party data, check the official page):

| GPU | Per hour, no zonal redundancy | Fits |
|---|---|---|
| L4 24 GB | about $0.67 (GPU only, plus CPU and memory) | LLM up to about 8B in FP16 or 14B in 4-bit, Whisper, most TTS |
| RTX PRO 6000 96 GB | about $3.19 (minimum config) | LLM up to about 32B in FP16 or 70B in 4-bit |

## Serving stack per model type

All model types use the same contract: an HTTP server on `$PORT` with a health route. This lets one Terraform module deploy any model.

| Type | Recommended server | Image | Example models |
|---|---|---|---|
| LLM | vLLM (OpenAI-compatible API) | `vllm/vllm-openai` | Qwen, Llama, Gemma, Mistral |
| STT | faster-whisper behind FastAPI | custom image | Whisper large-v3, distil-whisper |
| TTS | FastAPI wrapper per model | custom image | Kokoro, XTTS-v2, Piper, F5-TTS |
| Any custom | FastAPI or LitServe | custom image | anything with Python code |

Custom containers:

1. Start from a CUDA base image or from the vLLM image.
2. Add the Python code (pre-processing, post-processing, custom pipelines).
3. Build with Cloud Build. Push to Artifact Registry.
4. The Terraform module takes the image URL as a variable.

For an LLM that needs custom logic, keep vLLM as the engine. Put the custom code in a FastAPI app that uses the vLLM Python API in the same container. Do not write a new inference engine.

## Custom vLLM container

Yes, a custom vLLM container is possible. Cloud Run runs any OCI image. Start from the official `vllm/vllm-openai` image and add a layer. Do not build vLLM from source, because the build takes hours.

Select the smallest level that does the job:

| Level | What you change | Keep the OpenAI API | Use when |
|---|---|---|---|
| 1. Flags only | `args` in Terraform (`--model`, `--max-model-len`, `--quantization`, `--chat-template`, `--tool-call-parser`) | Yes | Most models |
| 2. Extra packages | `FROM vllm/vllm-openai` + `pip install` | Yes | Optional extras (`vllm[audio]`), tokenizers, custom chat templates |
| 3. vLLM plugin | A Python package with an entry point, installed in the image | Yes | New model architecture (`vllm.general_plugins` + `ModelRegistry.register_model`), extra HTTP routes (`vllm.endpoint_plugins`, opt-in) |
| 4. Own server | FastAPI app that calls vLLM `AsyncLLMEngine` in the same process | Only if you write it | Custom pre-processing, post-processing or pipelines (RAG, guards, multi-step) |

Example for level 2 and level 3:

```dockerfile
# Pin the version. The pip extras must match the base image version.
FROM vllm/vllm-openai:v0.11.0

RUN uv pip install --system "vllm[audio]==0.11.0"

# Level 3: own plugin package with entry point group "vllm.general_plugins"
COPY plugins/my_model_plugin /opt/my_model_plugin
RUN uv pip install --system /opt/my_model_plugin

ENTRYPOINT ["vllm", "serve"]
```

Example plugin registration:

```python
# my_model_plugin/__init__.py, registered in pyproject.toml:
# [project.entry-points."vllm.general_plugins"]
# register = "my_model_plugin:register"
def register():
    from vllm import ModelRegistry
    # A string reference loads the class lazily. This prevents CUDA errors in forked processes.
    ModelRegistry.register_model("MyModelForCausalLM", "my_model_plugin.model:MyModelForCausalLM")
```

Cloud Run notes:

1. The server must listen on port 8080, or you set the container port. Add `--port 8080 --host 0.0.0.0` to `args`.
2. Do not put weights in the image. The vLLM image is already about 10 GB or more. Load weights from the Cloud Storage volume (`--model /models/<name>`).
3. A large image makes cold start slower. Keep extra layers small.
4. Build the image with Cloud Build (`gcloud builds submit`). The build machine needs a large disk. No GPU is necessary for the build.
5. The Terraform module does not change. Only the `image` and `args` variables change.

## Model weights and cold start

A cold start has 3 parts: container start, weight load and engine start. Weight load is the largest part.

| Method | Cold start | Change model | Use when |
|---|---|---|---|
| Weights inside the image | Fast for small models | Rebuild the image | Small STT and TTS models (< 5 GB) |
| Cloud Storage bucket + Cloud Run volume mount (GCS FUSE) | Medium | Upload new files | Default for LLMs |
| Cloud Storage + vLLM Run:ai Model Streamer | Fastest for large LLMs | Upload new files | LLMs > 10 GB |
| Download from Hugging Face on start | Slow, not stable | Change a variable | Quick tests only |

Rules:

1. Put the bucket in the same region as the Cloud Run service.
2. Use Direct VPC egress for faster download from Cloud Storage.
3. Use a Cloud Run job or Cloud Build to copy weights from Hugging Face to the bucket one time.
4. Keep the Hugging Face token in Secret Manager.
5. Set a long startup probe (up to 30 min for large models).
6. Give the service account read-only access (`roles/storage.objectViewer`), not `storage.admin`.

## Terraform layout

Decision (2026-11-08): each model deployment has its own folder. Each folder is a separate Terraform root with its own state. You can apply or destroy one model and not touch the others.

```
infra/
  bootstrap/              # one time: APIs, state bucket, Artifact Registry, weights bucket, budget
  modules/
    model-service/        # shared: Cloud Run service (GPU optional) + SA + IAM + GCS volume
deployments/
  llm-a-gemma4-26b-vllm/  # A: stock vllm/vllm-openai image, flags only
    main.tf               # calls ../../infra/modules/model-service
    backend.tf            # state prefix = deployments/llm-a-gemma4-26b-vllm
    terraform.tfvars      # model path, GPU, args
    README.md             # how to call it, test request
  llm-b-qwen35-9b-fastapi/ # B: custom image with FastAPI + AsyncLLMEngine
    main.tf
    backend.tf
    terraform.tfvars
    image/                # Dockerfile, app.py, cloudbuild.yaml
    README.md
  stt-.../                # same pattern
  tts-.../                # same pattern
```

Rules for a deployment folder:

1. A folder with an `image/` subfolder builds its own image. A folder without it uses a public image.
2. Folder name: `<type>-<letter or short id>-<model>-<server>`.
3. To add a model, copy a folder and change `terraform.tfvars`.
4. To remove a model, run `terraform destroy` in its folder, then delete the folder.

Main resources:

- `google_project_service` for `run`, `artifactregistry`, `cloudbuild`, `secretmanager`, `storage`, `compute`.
- `google_storage_bucket` for Terraform state and for model weights.
- `google_artifact_registry_repository` for custom images.
- `google_service_account` per service, with read access to the weights bucket.
- `google_secret_manager_secret` for the Hugging Face token.
- `google_cloud_run_v2_service` per model.
- `google_cloud_run_v2_job` to copy weights into the bucket.

Sketch of the core module resource:

```hcl
resource "google_cloud_run_v2_service" "model" {
  name     = var.name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                = google_service_account.model.email
    gpu_zonal_redundancy_disabled  = true
    max_instance_request_concurrency = var.concurrency

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    node_selector {
      accelerator = var.gpu_type # "nvidia-l4" or "nvidia-rtx-pro-6000"
    }

    containers {
      image = var.image
      args  = var.args

      resources {
        limits = {
          cpu              = var.cpu
          memory           = var.memory
          "nvidia.com/gpu" = "1"
        }
        cpu_idle          = false
        startup_cpu_boost = true
      }

      startup_probe {
        tcp_socket { port = 8080 }
        period_seconds    = 10
        failure_threshold = 180
      }

      volume_mounts {
        name       = "weights"
        mount_path = "/models"
      }
    }

    volumes {
      name = "weights"
      gcs {
        bucket    = var.weights_bucket
        read_only = true
      }
    }
  }
}
```

Check the exact argument names against the current `hashicorp/google` provider docs before you use this sketch.

Access: keep services private (no `allUsers` invoker). Call them with an identity token (`gcloud auth print-identity-token`).

## Cost control

1. `min_instance_count = 0` on every service.
2. Low `max_instance_count` (1 or 2) for experiments.
3. Zonal redundancy off.
4. A billing budget with email alerts (`google_billing_budget`).
5. Remove a model with `terraform destroy -target` or by removing it from the model list.

## Open questions

1. Which GCP region? This sets which GPUs are available.
2. What is the monthly budget?
3. Which first models to deploy (1 LLM, 1 STT, 1 TTS)?
4. Do services need public access, or only access from your own machine?
5. Do you need streaming (LLM tokens, live STT), or only request and response?

## Next cards

1. Bootstrap: GCP project, APIs, Terraform state bucket, Artifact Registry, budget alert.
2. Terraform module `model-service` + `deployments/llm-a-gemma4-26b-vllm/`.
3. Model weights bucket + copy job from Hugging Face.
4. `deployments/llm-b-qwen35-9b-fastapi/` with a custom image.
5. STT and TTS deployments (see `03-speech-models.md`).
6. Cold start measurements: image vs GCS mount vs Model Streamer.

## Sources

- [Cloud Run GPU support for services](https://docs.cloud.google.com/run/docs/configuring/services/gpu)
- [Cloud Run GPU zonal redundancy](https://cloud.google.com/run/docs/configuring/services/gpu-zonal-redundancy)
- [Cloud Run GPU for jobs](https://docs.cloud.google.com/run/docs/configuring/jobs/gpu)
- [Codelab: Gemma 4 on Cloud Run with RTX 6000 Pro and vLLM](https://codelabs.developers.google.com/codelabs/cloud-run/cloud-run-gpu-rtx-pro-6000-gemma4-vllm)
- [Vertex AI autoscaling and scale to zero](https://docs.cloud.google.com/vertex-ai/docs/predictions/autoscaling)
- [vLLM plugin system](https://github.com/vllm-project/vllm/blob/main/docs/design/plugin_system.md)
- [vLLM out-of-tree model registration](https://github.com/vllm-project/vllm/blob/main/docs/contributing/model/registration.md)
- [vLLM Docker images](https://github.com/vllm-project/vllm/blob/main/docs/deployment/docker.md)
- [Run:ai Model Streamer on GKE](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/persistent-volumes/run-ai-model-streamer)
- [Cloud Run pricing overview (third party)](https://www.usage.ai/blogs/gcp/cloud-run-pricing/)
- [RTX PRO 6000 pricing (third party)](https://www.thundercompute.com/blog/nvidia-rtx-pro-6000-pricing)
- [Cloud Run GPU cold starts and costs (third party)](https://exodus.elim.io/blog/gpus-on-cloud-run)
