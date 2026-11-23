# Docs

Short guides with diagrams. Details are in [`infra/README.md`](../infra/README.md). Commands for one model are in the README of its deployment.

| Read | To learn |
|---|---|
| This page | The system map, the 2 layers, the weights flow |
| [scripts.md](scripts.md) | What each script in `scripts/` does, and in which order to run them |
| [gateway-and-streaming.md](gateway-and-streaming.md) | What API Gateway does, and how streaming works |
| [backends.md](backends.md) | Cloud Run and Vertex AI, cold start and cost, Slack messages at scale up and down |
| [auth-and-ui.md](auth-and-ui.md) | Keys and tokens, the test UI, common errors |

Older notes: [`research/`](research/) (options and prices) and [`specs/`](specs/) (design and plans, dated).

## System map

![System map: public gateway, private backends, weights flow](diagrams/system-map.svg)

Source: [`diagrams/system-map.d2`](diagrams/system-map.d2). After a change, run `d2 --layout elk --pad 20 docs/diagrams/system-map.d2 docs/diagrams/system-map.svg`.

Only the gateway is public. Every backend is private and scales to zero. Dashed lines show how the services read the weights. The details of the weights flow are in the diagram below.

## Two layers

```mermaid
flowchart LR
    core["<b>infra/core</b><br/>apply once per project<br/>―――<br/>APIs, budget, registry repos<br/>buckets: weights, UI<br/>weights-copy job, hf-token secret<br/>API Gateway APIs, 1 shared API key<br/>Slack channel models-slack"]
    dep["<b>deployments/#lt;name#gt;</b><br/>one folder and one state per model<br/>―――<br/>module model, model-service or vertex-model<br/>alerts.tf, output ui"]
    core -->|"apply first"| dep

    classDef layer fill:#f8fafc,stroke:#475569,color:#111
    class core,dep layer
```

| Folder | Content |
|---|---|
| `infra/core/` | Shared setup. Apply once. |
| `infra/modules/` | `model` (1 model on a list of platforms, with `platform-vertex`, `gateway`, `cors-proxy`), `model-service` (Cloud Run), `vertex-model` (Vertex AI), `scale-alerts` (Slack) |
| `deployments/<name>/` | One model: image, flags, gateway, Slack alerts |
| `scripts/` | Python helpers |
| `ui/` | React test UI |

State and runs are on HCP Terraform. Each root has its own workspace.

## Weights flow

```mermaid
flowchart LR
    HF["Hugging Face"] --> J["job weights-copy<br/>(HF_REPO, TARGET_DIR)"]
    J --> B[("gs://project-models/TARGET_DIR/")]
    B -->|"/models mount"| CR["Cloud Run"]
    B -->|"AIP_STORAGE_URI"| VX["Vertex AI"]
    B -->|"runpod-weights.py<br/>(S3 API)"| NV[("Runpod network volume")]
    NV -->|"/runpod-volume"| RP["Runpod worker"]
```

`local.model_dir` in a deployment must match `TARGET_DIR` of the job. A Runpod worker with a volume (STT-A) reads the same folder from `/runpod-volume/<TARGET_DIR>/`. LLM-A on Runpod has no volume: vLLM downloads from Hugging Face at start.
