# custom-models

Terraform code that serves open-weight models as private, scale-to-zero services on Google Cloud (project `custom-models-inference`, region `us-central1`). A static test UI calls the models through API Gateway.

| Model | Folder | Runs on |
|---|---|---|
| LLM: Gemma 4 12B (vLLM) | `deployments/llm-a-gemma4-12b-vllm-vertex` | Vertex AI, 1 L4 GPU |
| TTS: Kokoro | `deployments/tts-a-kokoro-cpu` | Cloud Run, CPU |

A GPU replica costs about $1.34 per hour while it runs. A budget alert does not stop spend.

## Folders

| Folder | Content |
|---|---|
| `infra/core/` | Shared setup. Apply it once per project. It makes the APIs, the buckets, the Artifact Registry repos, the budget, the `weights-copy` job, the API Gateway APIs, the shared API key and the `cors-preflight` service. |
| `infra/modules/` | `model-service` (Cloud Run) and `vertex-model` (Vertex AI). Deployments use them. |
| `deployments/<name>/` | One folder and one state per model. It has the image, the flags and the gateway. |
| `scripts/` | Python helpers: `check.py`, `preflight.py`, `hcp-sync.py`, `vertex.py`, `gateway-streaming.py`, `ui-deploy.py`. |
| `ui/` | The test UI (React and Vite). |
| `docs/` | Research and design notes. |

All details are in [`infra/README.md`](infra/README.md). Rules for the agent are in [`CLAUDE.md`](CLAUDE.md).

## Deploy

State and runs are on HCP Terraform. Secrets are in the git-ignored `.env` (template: `.env.example`). Do not print or commit it.

Setup, once:

1. Copy `.env.example` to `.env` and fill it in. Run `direnv allow`.
2. Run `./scripts/hcp-sync.py`. Run it again after each `.env` change.

Before each apply, run `./scripts/check.py` (local checks, no credentials) and `direnv exec . ./scripts/preflight.py` (read-only checks against the real project). Fix every FAIL. The README of a deployment adds the preflight flags for that model.

Steps, in this order:

1. **Core.** `cd infra/core && terraform init && terraform plan && terraform apply`.
   Check: the plan says "No changes" after the apply.
2. **Each model.** Follow the README of its folder. It has the exact commands for that model: the weights copy, the apply, the model deploy (Vertex AI), the gateway streaming and the test call.
   - [`deployments/llm-a-gemma4-12b-vllm-vertex`](deployments/llm-a-gemma4-12b-vllm-vertex/README.md)
   - [`deployments/tts-a-kokoro-cpu`](deployments/tts-a-kokoro-cpu/README.md)
3. **UI.** `./scripts/ui-deploy.py`. It writes `models.json`, builds the UI and uploads it. Run it after each deployment apply or `gateway-streaming.py` run, because the gateway URL can change.

To stop the cost of a Vertex AI model, undeploy it (see the README of the deployment).

## Test UI

URL: <https://storage.googleapis.com/custom-models-inference-ui/index.html>

1. Get the API key: `cd infra/core && terraform output -raw api_key`.
2. Open the URL. Enter the key. The browser keeps it.
3. Pick a tab, one per model. Send a chat message (LLM) or text (TTS).
4. The LLM scales to zero. The first call can wait for a cold start of several minutes. The UI retries until the model answers.
5. Each panel shows the timing and the `curl` command for the same call. The command uses `$KEY`.

A new gateway URL is not in the UI until you run `./scripts/ui-deploy.py` (or `--config-only` when the UI code did not change).

Local work: `cd ui && npm install && npm test && npm run build`. For a mock backend, run `npm run mock` and `npm run dev`. To add a model tab, use the `model-ui` skill (`.claude/skills/model-ui/SKILL.md`).
