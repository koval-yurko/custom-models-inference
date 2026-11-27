# Model weights storage: options and prices on Runpod, Modal and GCP

Date: 2026-11-27. Card: "LLM-B on Runpod: build image 0.2.3 with the /ping and IPv4 fix, unpark and test".

This document compares the places where a GPU worker can get its model weights. It covers storage price, network (egress) price, cache behavior and the effect on cold starts. All prices are in USD.

## Sources and how the prices were read

| Provider | Source | Read on |
|---|---|---|
| GCP Cloud Storage, Artifact Registry | Cloud Billing Catalog API (`cloudbilling.googleapis.com/v1/services/<id>/skus`), the same data as the price pages | 2026-11-27 |
| Runpod | docs.runpod.io (Network volumes, Pricing, Cached models, Global volumes), the Runpod catalog API, our own billing records (`/v2/billing`) | 2026-11-27 |
| Modal | modal.com/pricing, modal.com/docs/guide/volumes, modal.com/docs/guide/model-weights | 2026-11-27 |

Prices change. Read them again before a large change.

## Our numbers

| Item | Size |
|---|---|
| LLM-B weights (`RedHatAI/Qwen3.5-9B-FP8-dynamic`) | about 14 GB (13 GiB) |
| LLM-B image `llm-b-qwen35-9b-fastapi:0.2.3` (vLLM base + `app.py`) | 9.74 GB compressed (from the image manifest) |
| STT-A weights (ASR, aligner, Pyannote) | under 20 GB (the Runpod volume is 20 GB) |
| Cold starts | about 1 to 3 per model per day during tests |

## Price reference

### GCP

| Item | Price |
|---|---|
| Cloud Storage, Standard, `us-central1` | $0.02 per GiB per month (first 5 GiB free) |
| Cloud Storage download to the internet (all destinations except Asia and Australia) | first 100 GiB per month free, then $0.12 per GiB, $0.11 above 1 TiB, $0.08 above 10 TiB |
| Artifact Registry storage | first 0.5 GiB free, then $0.10 per GiB per month |
| Artifact Registry internet egress, `us-central1` to Europe ("Intercontinental, excl. Oceania, Africa and China") | $0.12 per GiB for the first 10 TiB, then $0.085, then $0.08 |
| Artifact Registry internet egress, North America to North America | $0.105 per GiB |
| Artifact Registry egress in the same region (Vertex AI, Cloud Run in `us-central1`) | $0 |
| Artifact Registry egress to Google APIs | $0 |

### Runpod

| Item | Price |
|---|---|
| Network volume, Standard | $0.07 per GB per month for the first 1 TB, $0.05 above. Billed hourly, for the reserved size, also when no worker runs |
| Network volume, High-performance | a premium over Standard. The price differs per data center and shows only in the console |
| Global volume (beta) | per GB stored (price not in the docs; the console shows it), plus $0.005 per 1,000 write requests and $0.0005 per 1,000 read requests |
| Cached models (Model Store, beta) | $0. The download time is not billed |
| Model Repository (`runpodctl model`, beta) | not published |
| Container disk of a Serverless worker | billed in 5-minute steps while the worker runs. Our records show a few cents per day |
| Data transfer in and out of Runpod | $0 ("there are no ingress or egress fees") |

### Modal

| Item | Price |
|---|---|
| Volume storage | $0.09 per GiB per month, with 1 TiB per month free |
| Network egress | $0.04 per GiB. The Starter plan includes 1 TiB per month free |
| Ingress | no price listed |
| Image storage | no price listed |

## Options

### 1. GCP: Cloud Storage bucket in the same region (Vertex AI and Cloud Run, now)

How it works: the weights are in `gs://<project>-models/<folder>/`. Vertex AI streams them at start (`runai_streamer`). Cloud Run mounts the bucket with GCS FUSE at `/models`. The GPUs run in `us-central1`, the same region as the bucket.

- Price for LLM-B: about $0.26 per month. Same-region reads cost $0.
- Good:
  - 1 copy for every replica in the region.
  - No network cost.
  - The copy job (`weights-copy`) already exists.
- Bad:
  - Only for compute in the same region.
  - A GPU from another provider pays internet egress to read it (see option 7).

### 2. Modal Volume (STT-A on Modal, now)

How it works: the weights are on a Modal Volume. Modal says Volumes are distributed for its global compute pool, so we do not manage copies per region.

- Price for STT-A: $0, because we use far less than the 1 TiB free allowance.
- Good:
  - 1 copy for all Modal regions.
  - Up to 2.5 GB/s read (not guaranteed).
  - Modal recommends this way for weights.
- Bad:
  - Modal only.
  - Data deleted from a Volume can stay billed for up to 4 days (only matters above the free allowance).
  - Modal pulls our image from Artifact Registry (`registry_pull_key`). Each pull pays Artifact Registry egress at $0.105 to $0.12 per GiB. Modal caches built images, so this happens at a build or a new image, not at every cold start.

### 3. Runpod network volume, 1 per data center (LLM-B and STT-A on Runpod, now)

How it works: 1 volume per data center. `scripts/runpod-weights.py` copies the weights from GCS with the Runpod S3 API. A worker can start only in a data center that has a volume.

- Price at the time of this report: 6 volumes, 180 GB in total, $0.33 per day (about $10 per month). LLM-B: 3 × 40 GB = $8.40 per month. STT-A: 3 × 20 GB = $4.20 per month.
- Price since 2026-11-27: 2 volumes, both in EU-RO-1. LLM-B: 40 GB = $2.80 per month. STT-A: 20 GB = $1.40 per month. The volumes in EU-CZ-1 and EUR-IS-1 are deleted.
- Good:
  - Fast and predictable cold start: the weights are in the same data center.
  - Full file system.
  - Works for every model, also with several models in 1 image (STT-A).
- Bad:
  - We pay for every copy, and for the reserved size, not the used size.
  - GPUs only in the data centers with a volume (L4 and RTX 4090 only in EU-RO-1 and EUR-IS-1, RTX 3090 only in EU-CZ-1).
  - Volumes cannot shrink.
  - The S3 upload needs about 2 times the largest file while it runs, so LLM-B needs 40 GB, not 14 GB.
  - At a $0 balance, Runpod can delete the volume and its data.
  - The copy to each data center is our job.

### 4. Runpod Global volume (beta)

How it works: 1 volume that is not tied to a data center. Workers in any data center mount it at `/runpod-volume`, the same path as a network volume, so `app.py` needs no change.

- Price: per GB stored, plus requests. The per-GB price is not in the docs.
- Good:
  - 1 copy, workers in any data center with a free GPU.
  - No size to reserve.
  - No code change.
- Bad:
  - Beta.
  - It is object storage: slower than a network volume. Runpod measured 26 to 51 s to restore a 3 GB model before SDK 2.0, against 5 s from a network volume.
  - No file locks or atomic rename.
  - 1 global volume per endpoint, and not together with network volumes.
  - At a $0 balance it is deleted after 15 days.
  - The Terraform provider support is not checked.

### 5. Runpod cached models (Model Store, beta)

How it works: the endpoint points at a Hugging Face repo. Runpod caches it on its hosts and in the data center, and starts workers on hosts that already have it. Workers find it at `/runpod-volume/huggingface-cache/hub/`.

- Price: $0 for storage, and the download is not billed.
- Good:
  - No volume, no copy job, no data-center limit.
  - Cold starts are in seconds on a host that has the model.
- Bad:
  - Beta.
  - 1 cached model per endpoint, so this does not fit STT-A (3 models).
  - The model must be on Hugging Face.
  - Runpod downloads every quantization in the repo.
  - On a host without the model, the worker waits for the download, and the call waits in the queue.
  - The cache is "best-effort", so cold starts can differ between workers.
  - The Terraform provider support is not checked.
- Fit: LLM-B (1 Hugging Face repo).

### 6. Weights in the Docker image

How it works: the build copies the weights into the image. Runpod (or Modal) pulls the image before the worker starts.

- Price for LLM-B: the image grows from 9.74 GB to about 24 GB (22 GiB).
  - Artifact Registry storage: about $2.20 per month for each image version we keep.
  - Each pull to a new Runpod host in Europe: 22 GiB × $0.12 = about $2.65.
- Good:
  - Works on every provider.
  - No volume and no data-center limit.
  - Runpod lists it as the way for models that are not on Hugging Face.
  - Runpod says the model is "ready to serve requests quickly after billing begins", so the pull seems to happen before billing starts.
- Bad:
  - Each new host pays the full pull.
  - Each code change makes a new 24 GB image, and every host pulls it again.
  - Builds and pushes are slow.
  - Each kept image version is billed.

### 7. Download from the GCS bucket at each cold start

How it works: `app.py` downloads the weights from `gs://<project>-models/...` to the local disk at start, with a read-only GCS key kept as a Runpod secret.

- Price for LLM-B:
  - GCS storage about $0.26 per month.
  - Each cold start downloads 13 GiB. The first 100 GiB per month are free (about 7 cold starts). After that, each cold start costs about $1.56.
  - We also pay for the GPU time while the download runs, because our code does it after billing starts.
- Good:
  - 1 copy for all providers.
  - No Runpod storage.
  - No data-center limit.
- Bad:
  - Slower cold start. Runpod measured a 7B model at 98 s with a download, against 68 s from a volume.
  - Egress cost after the free 100 GiB.
  - Needs code and a GCS key on Runpod.

### 8. Runpod Model Repository (`runpodctl model add`, beta)

How it works: we upload our own weights once. Runpod stores, versions and copies them to hosts.

- Price: not published.
- Good: not tied to a data center, and versioned.
- Bad: Runpod's own guide says that the way a worker loads an uploaded model at runtime is not documented yet. Not usable now.

## The image pull (applies to every Runpod option)

Our images are in Artifact Registry in `us-central1`. A Runpod host in Europe that pulls an image pays internet egress at $0.12 per GiB.

- Today, each new host that pulls the LLM-B image pays 9.74 GB, which is about $1.09.
- A host that already has the layers pulls only the changed layers, nearly $0. The worker log on 2026-11-26 showed "Already exists" for almost all layers.
- An earlier card chose Artifact Registry over a copy on GHCR or Docker Hub (project memory, decision of 2026-11-23). A change is a decision for the user.

## Summary for LLM-B on Runpod

| Option | Fixed cost per month | Cost per cold start or new host (on top of GPU time) | Data-center limit | Ready |
|---|---|---|---|---|
| 3. Network volumes, 3 copies (until 2026-11-27) | $8.40 | about $1.09 image pull, new host only | 3 data centers | yes |
| 3. Network volume, 1 copy (EU-RO-1, now) | $2.80 | about $1.09 image pull, new host only | 1 data center | yes |
| 4. Global volume (beta) | per GB price not published | about $1.09 image pull, new host only | none | beta, not tested |
| 5. Cached models (beta) | $0 | about $1.09 image pull, new host only | none | beta |
| 6. Weights in the image | about $2.20 per kept image version | about $2.65 image pull, new host only | none | yes |
| 7. Download from GCS | about $0.26 | about $1.09 image pull on a new host, plus about $1.56 per cold start after 100 GiB per month | none | needs code |
| 8. Model Repository | not published | not published | none | no |

For comparison: LLM-B on Vertex AI (option 1) costs about $0.26 per month for storage and $0 for network. STT-A on Modal (option 2) costs $0.

## Recommendation

Status 2026-11-27: each model on Runpod now uses 1 network volume in EU-RO-1 (option 3, 1 copy). The cached models test (option 5) for LLM-B is still open. LLM-B answered from the EU-RO-1 volume with a 411 s cold start (LLM-B README, "Cold start").

1. **LLM-B on Runpod:** use cached models (option 5), and delete the 3 network volumes. This saves about $8.40 per month and removes the data-center limit. Test 2 or 3 cold starts first. If the cache makes cold starts too slow, use 1 network volume in EU-RO-1 (option 3, $2.80 per month).
2. **STT-A on Runpod:** keep 1 network volume in EU-RO-1 and delete the other 2. This saves $2.80 per month. Test a Global volume (option 4) later, when its price and its Terraform support are known.
3. **Vertex AI, Cloud Run and Modal:** no change. They already use 1 cheap or free copy.
4. **Runpod account:** turn on Auto-Pay or low-balance alerts. At $0, Runpod starts no worker, and it can delete volumes (network volumes after a while, Global volumes after 15 days). `./scripts/preflight.py` now checks the balance before each apply.

## Open points

- The per-GB price of a Runpod Global volume (read it in the console).
- The Terraform provider support for cached models (`modelReferences`) and Global volumes on `runpod_serverless_endpoint`.
- The real Artifact Registry egress cost so far (in the GCP billing data).
- The Modal Volume region rule: the docs say "distributed by default" but do not say plainly that every region can mount it.
