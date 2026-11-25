# Research: Modal as the GPU platform for STT-A

Date: 2026-11-24, spike on 2026-11-25. Card: "Investigate Modal as a GPU platform for STT-A (scale to zero, own image)". Status: research done, spike done.

Sources: the Modal docs and pricing pages, read on 2026-11-24 (SDK 1.6.4 from 2026-11-11). Some SDK reference pages redirect to empty pages, so we read those facts in Modal's full docs file https://modal.com/llms-full.txt. The numbers in "Spike results" are our measurements. The other cold start numbers are Modal's claims. The general Modal facts from 2026-11-22 are in `07-other-gpu-providers.md` (section "Modal"). This document adds the STT-A details.

## Why

STT-A has no working GPU platform:

- Vertex AI in `us-central1` often has no L4 stock (`04-vertex-ai.md`).
- On Runpod, the load balancer never sent a request to our own-image workers (card 39dd8cf9, `deployments/stt-a-qwen3-asr-diar/README.md`, cold start table). Later, all 24 GB GPUs in the pinned EU data centers were out of stock. The Runpod endpoint is parked (`workers_max = 0`).

## Recommendation

**Go.** The spike passed: the unchanged STT-A image answered on Modal with the right text and 2 speakers, and each cold start got a GPU in 4 to 7 s. Next: the integration steps 2 to 6 below.

Reasons:

1. GPU capacity: 6 of 6 container starts got a GPU (always an A10G) 4 to 7 s after the request. On Runpod and Vertex AI, the same model waited many minutes or got no GPU.
2. A request at 0 containers waits for the container. The first answer came 157 to 169 s after the request, below the 280 s proxy cold wait.
3. Our Artifact Registry image runs without a change to the engine code. Modal needs 2 small image layers (`entrypoint([])` and a `python` link), added in the Modal app file.
4. Idle cost is $0. The whole spike (4 cold starts, 2 warm calls, image builds, the Volume fill) cost $0.67, paid by the free credit.

What the integration must handle:

- A cold call passes the 150 s HTTP limit, so Modal answers HTTP 303 at about 150 s. The CORS proxy must follow it (Q5). In the spike, 1 redirect was enough every time.
- The cold start is 2 times the Runpod time (about 145 s against 65 to 78 s to `models ready`). See "Spike results" for where the time goes.
- Start crash (found and fixed on 2026-11-25): the engine ended with SIGSEGV on most starts. Cause: Modal runs the container with `ulimit -s unlimited`, so glibc gives each new thread only a 2 MB stack (8 MB on a normal Docker host). The engine loads its models in a thread, and that load overflowed the stack. Fix: `modal_app.py` starts the engine with a 64 MB stack limit. See "Crash cause".

## Spike results (2026-11-25)

Setup: a spike app file (way A of Q3; it became `scripts/platforms/modal_app.py`) with image `stt-a-qwen3-asr-diar:0.2.4`, `gpu=["L4", "A10"]`, 4 cores, 32 GiB, `scaledown_window=60`, `max_containers=1`, no region pin, proxy auth on. The weights were on the Modal Volume `stt-a-weights`. The call was a small Python script: `POST /v1beta/interactions` with the stored 2-speaker test file (`360fec17-26be-450d-9dcd-30f2674e9776`, 400 KB WAV) inline. It follows a 303 by hand, as the proxy will. The call went from the laptop to the Modal URL directly, not through the gateway.

| Call | Request to container start | Container start to `models ready` | Request to answer | Notes |
|---|---|---|---|---|
| Cold 1 | 7 s | 153.0 s | 169.0 s (303 at 161 s, then 200) | First start of the image on Modal |
| Warm (2 calls) | - | - | 3.1 s each | Bearer header, and `Modal-Key` with `Modal-Secret` |
| Cold 2 | 4 s | 143.9 s | 157.5 s (303 at 151 s, then 200) | |
| Cold 3 | 5 s | 149.6 s | 163.0 s (303 at 155 s, then 200) | vLLM compile cache on a Volume, first fill |
| Cold 4 | 4 s | 130.1 s (3rd container) | 354.8 s (303 at 345 s, then 200) | With the cache: the engine ended with signal 11 (segfault) in 2 containers. Modal started a new one each time |

Every answer: HTTP 200, the same text each time ("Hello. This is the first speaker. ..."), 37 `word_info` items, speakers `spk_1` and `spk_2`, `setup.platform` `modal`, `setup.gpu` `NVIDIA A10G`.

Other findings:

- GPU: Modal gave an A10G (24 GB) to all 6 containers, never the L4 that is first in the list. The billing rates list "Nvidia A10G: $1.10 / hour". So plan the cost with the A10G.
- Where the cold start time goes (cold 1): 32 s of Python imports before vLLM starts, 53 s of vLLM engine start (the weights read from the Volume took only 1.7 to 5.9 s), 26 s of `torch.compile`, 6 s of CUDA graph capture, and about 10 s for the aligner and Pyannote.
- Compile cache: with `VLLM_CACHE_ROOT` on a second Volume, vLLM loaded the compiled graphs ("Directly load the compiled graph(s) ... from the cache") and `torch.compile` dropped from 26 s to 11 to 13 s. But 2 of 3 starts with the cache ended in a segfault after the vLLM start, and none of the 3 starts without the cache did. Do not use the cache.
- Image: the first deploy failed with "We were unable to determine the version of Python installed in the Image". The vLLM base image has `python3` but no `python`. A Modal layer that links `python` to `python3` fixed it. The image ENTRYPOINT must be removed (`.entrypoint([])`): it starts the server and does not run the arguments that Modal passes.
- The image pull from Artifact Registry at the first deploy took 243 s (build time, not cold start time). Later deploys reused it.
- Volume fill: the 3 Hugging Face repos (the `HF_REPO` values of the STT-A README) took 56 s inside Modal, including the image build of the copy function. The file list matches the GCS copy.
- Auth: without a token the URL answers 401. `Authorization: Bearer wk-<id>.ws-<secret>` works, so `auth_header()` in `cors_proxy.py` needs no change.
- Scale to zero: with `scaledown_window=60`, the container was gone about 2 minutes after the last answer.
- Cost: metered $0.67 for the whole spike ($0.65 the app, $0.02 the Volumes), billed $0.00 (the free credit).
- Clean-up: the app is stopped, the cache Volume, the proxy token and the spike key of `runpod-pull` are deleted. The Volume `stt-a-weights` stays for the integration.

## Integration test (2026-11-25)

Setup: the integration of steps 2 to 6 (`platform-modal`, `scripts/platforms/modal.py` and `modal_app.py`), image `stt-a-qwen3-asr-diar:0.2.3`, applied with `infra/core` and STT-A. The call was `POST <gateway>/modal/v1beta/files/360fec17-26be-450d-9dcd-30f2674e9776/transcribe` with the API key: gateway, CORS proxy (Modal proxy token, 303 follow), Modal.

- First cold call: 5 of 5 container starts ended with SIGSEGV (engine exit -11), each right after vLLM was ready, while the aligner and Pyannote load. The proxy answered 429 after 281 s and again after 592 s. The app was stopped by hand.
- New deploy with `PYTHONFAULTHANDLER=1` and a `GET /health` direct to the Modal URL: the container started on an A10G, the health call got the 303 at 151 s, and the engine became ready. No crash.
- Then, warm: `transcribe` through the gateway returned 201 in 9 s (without `diarization`: no speakers), and 201 in 3 s with `"diarization": true`: 37 `word_info` items, `spk_1` (23 words) and `spk_2` (14 words), `setup.platform` `modal`, `setup.gpu` `NVIDIA A10G`. The versions are saved.
- The cause of the crash was not known at this point. It is not the compile cache (no cache in this test). `PYTHONFAULTHANDLER=1` was turned on for every Modal model, so a crash prints its stack. See "Crash cause".
- Cost of the day (spike and this test): $0.94 metered, $0.00 billed (free credit).
- Second run (image 0.2.5, built from this branch: 0.2.3 had no Slack code, so no Slack message came from Modal before). Slack "ready" and "scaled to 0" work. Cold `transcribe` through the gateway: `201` after about 940 s, after 3 tries with `429`. GPU of each start, from the `nvidia-smi -L` line: plain A10 crashed 7 of 7 over the day, L4 crashed 1 of 2, A10G was good 3 of 3. So the crash is not only on one GPU type, but A10 is the worst.
- First decision (user, 2026-11-25, later changed, see below): STT-A uses `gpus = ["L4"]`, no fallback. L4 costs $0.80/h against $1.10/h for A10 (and A10G). A start waits for a free L4. The crash cause was found later the same day: see "Crash cause".

## Crash cause (2026-11-25)

Symptom: on L4 the engine ended with SIGSEGV (exit -11) on every start in the afternoon: 3 of 3 starts of the deployed app through the gateway (a cold `transcribe` got only `429` for about 20 minutes), and 4 of 4 trial starts. Most crashes came right after vLLM was ready, while the aligner and Pyannote load. The Modal log lost the last lines of a crashed container, so most crashes showed no stack.

Method: a trial app (not in the repo) started the engine on L4 in separate containers. It read all engine output through a pipe, so the `faulthandler` stack of a crash was kept. Each case changed 1 thing:

| Case | What changed | Starts | SIGSEGV |
|---|---|---|---|
| `server` | Nothing (the same command as the real app) | 4 | 4 |
| `localcopy` | The weights copied from the Volume to local disk first | 1 | 1 |
| `loadonly` | The 3 models loaded in the main thread, no HTTP server | 1 | 0 |
| `bigstack` | `threading.stack_size(64 MB)` before any thread starts | 5 | 0 (3 ready, 2 failed for another reason, see below) |

Evidence:

- The `localcopy` crash stack: the current thread was the load thread of `asyncio.to_thread`, in `pyannote/audio/core/inference.py` line 134 (`Powerset(...)`, a small object). So the crash is not in deep code and not in a file read from the Volume.
- In the container, `ulimit -s` is `unlimited` and the kernel is `4.19.0-gvisor`. With an unlimited stack limit, glibc gives each new thread a 2 MB stack. A normal Docker host has `ulimit -s 8192`, so its threads get 8 MB. This is why the same image never crashed on Vertex AI or Runpod.
- Cause: the model load runs in a thread with a 2 MB stack, and native code in the load (torch, CUDA, vLLM) needs more. The overflow is a SIGSEGV. The crash point moves, because it depends on how deep the native calls go at that moment.
- The 2 `bigstack` failures were not crashes: vLLM stopped at start with "Free memory on device cuda:0 (2.53/22.08 GiB) on startup is less than desired GPU memory utilization". Another process held about 19.5 GB of that GPU. The most likely cause is an engine process of an earlier crashed container. With no more crashes, this must not come again. Watch for it.

Fix: `scripts/platforms/modal_app.py` starts the engine with `RLIMIT_STACK` = 64 MB (`preexec_fn`). glibc reads the limit when the process starts, so every thread of the engine gets 64 MB. The change is in the Modal app file only: no new image, no change on Vertex AI or Runpod.

Retest after the fix (same day, image 0.2.5, `gpus = ["L4"]`): a cold `transcribe` through the gateway `/modal/` path returned `201` after 1058 s, on try 4 (3 tries got `429`). Modal had no free L4 for about 15 minutes: the container started at 17:55:48 for a call sent at 17:40:38. The container became ready 132.9 s after its start, with no crash. The answer `setup` shows `"platform": "modal"` and `"gpu": "NVIDIA L4"`. Slack got "ready" at 17:58:00 and "scaled to 0" at 18:04:04: 5 min 48 s after the answer at 17:58:16, with `idle_seconds = 300`. Modal showed 0 containers at 18:04:20. So the open risk is now the L4 stock, not the crash: in the afternoon, a start waited 3 to 15 minutes for an L4, where A10 and A10G started in 4 to 7 s in the morning. If that wait stays, allow A10G as a second GPU type. It costs $1.10/h against $0.80/h, but only for the starts that get one. Plain A10 starts crashed 7 of 7 before the fix (see the A10 retest below).

Retest on A10-class GPUs (same day, trial app, `gpu="A10"`, so Modal gives a plain A10 or an A10G): 5 of 5 starts became ready, with no crash. With the fix: A10G ready in 145 s and 88 s, plain A10 in 109 s and 111 s. Plain A10 starts crashed 7 of 7 before the fix, so the fix works on that GPU too. 1 start without the fix also became ready, on an A10G (A10G starts without the fix were good 4 of 4 over the day, so the crash rate depends on the GPU type). 1 A10G had 9990 MiB of its memory in use at start, and the engine still started, because vLLM needs about 11 GB of the 22 GB. The GPU memory left in use by an earlier container is a Modal-side effect; watch for vLLM "Free memory on device" errors at start.

Final decision (user, 2026-11-25, after these retests): STT-A uses `gpus = ["L4", "A10"]`. Modal tries an L4 first ($0.80/h) and takes an A10 or A10G ($1.10/h) when no L4 is free. The thread stack fix makes all 3 GPU types start without a crash, and the fallback removes the long L4 wait.

## Answers

### Q1. GPU capacity

- 24 GB class GPUs on Modal: L4 ($0.000222 per s, about $0.80 per h) and A10 ($0.000306 per s, about $1.10 per h). The Modal type "A10" is an NVIDIA A10G: the spike container reported "NVIDIA A10G", and the billing rates list "Nvidia A10G: $1.10 / hour". L40S has 48 GB ($0.000542 per s, about $1.95 per h). [1][2]
- A list of GPU types is a fallback list: "Modal respects the ordering of this list and will try to allocate the most preferred GPU type before falling back". Use `gpu=["L4", "A10"]`, with `"L40S"` as an optional third choice. All 3 run bf16. [2]
- Regions: by default Modal picks the region. A pinned region costs more: ×1.15 for a broad region (`us`, `eu`, `ap`) and ×1.75 for a narrow region (for example `us-central`). Do not pin a region. [3]
- Plan limits: Starter plan $0 per month with $30 credit per month, 100 containers, 10 GPUs at once. Team plan $250 per month, 50 GPUs at once. A GPU needs a payment card on file. STT-A needs 1 GPU. [1][2]
- How often a cold start waits for a GPU: **not published**. The docs only say that more than 2 GPUs per container "will usually result in larger wait times". An outside benchmark (500 cold calls, A100, weights cached) gave a median Modal cold start of 1.8 s, but it measured no GPU wait and no failure rate. The site has a Runpod affiliate link. [2][4]
- Measured (spike): 6 of 6 container starts began 4 to 7 s after the request. All got an A10G, none the L4 that was first in the list. 1 day of tests is a small sample, so watch the GPU wait in the Slack "ready" times after the integration.

### Q2. Scale to zero and cold start

- Scale to zero is the default. `scaledown_window` sets the idle time: default 60 s, from 2 s to 20 min. (The `autoscaler.update` reference says 2 to 3600 s. Use 20 min as the limit until a test shows more.) Other settings: `min_containers`, `max_containers`, `buffer_containers`. [5][6]
- Use `scaledown_window = 300` (the `idle_seconds` of the STT-A spec) and `max_containers = 1`, as on the other platforms.
- Memory snapshots (`enable_memory_snapshot=True`) make the start "3-10x faster", but they "do not speed up model loading from storage". GPU memory snapshots are alpha and do not work well with `torch.compile`. vLLM in our image uses CUDA graphs. Do not use snapshots in the first version. [7]
- Measured cold start for STT-A (6.58 GB of weights, A10G): 130 to 153 s from container start to `models ready`, 157 to 169 s from the request to the answer. The weights read from the Volume took only 1.7 to 5.9 s; the rest is Python imports, the vLLM engine start and `torch.compile` (see "Spike results"). This is about 2 times the 65 to 78 s on a Runpod RTX 4090. [6][8]
- A faster cold start is possible later, but not needed: the answer comes well inside the 280 s proxy cold wait. The vLLM compile cache on a Volume saved about 15 s. It is out, because it adds a second Volume for a small gain. (The segfaults of that test had another cause: see "Crash cause".)
- Warm pools: `min_containers = 1` keeps 1 container warm, but it bills all the time (about $1.55 per h, see Q7). The anti-goals of this repo forbid min instances above 0, so do not use it.

### Q3. Own image

Modal can pull our image from Artifact Registry. There are 2 ways to run it:

| | A. Function with `@modal.web_server` (recommended) | B. Modal Server (`modal server deploy --image`) |
|---|---|---|
| Image | `modal.Image.from_registry("<region>-docker.pkg.dev/<project>/models/stt-a-qwen3-asr-diar:<tag>", secret=...)`. The secret has the key `SERVICE_ACCOUNT_JSON` [9] | The same image. "The image needs no Python and no Modal client". It runs the image ENTRYPOINT [10] |
| Code | 1 small Python app file. `@modal.enter` starts `python3 -m speech_engine.main` and waits for `/health` 200 | No app file. Only CLI flags |
| Request at 0 containers | Waits for the container | HTTP 503. The client must retry [10] |
| Start limit | `startup_timeout` (set 600 s) | `startup_timeout` 30 s by default [10] |
| Request limit | 150 s, then HTTP 303 (Q5) | "Request timeouts cannot be customized within Modal" [10] |

Way A is recommended, because a request waits for the container and the engine code needs no change. Details:

- Modal does not run the image ENTRYPOINT for a Function. The image needs `python` and `pip` on the `$PATH`; else `add_python` adds them [9]. Measured: our base image has `python3` but no `python`, and the deploy failed. 1 Modal layer that links `python` and `pip` fixed it. Also remove the image ENTRYPOINT with `.entrypoint([])`.
- The engine opens the port at once and loads the models in a thread. While it loads, `/v1beta/interactions` answers 503 and `/health` answers 503 (on all platforms except Runpod). So the app file must not let a request in before the load ends. `@modal.enter` runs before the container takes requests: it starts the engine and polls `/health` until 200. Then `@modal.web_server(8080)` only points Modal at the open port.
- Container contract: the adapter sets `PORT=8080`, `MODEL=/models/stt-a-qwen3-asr-diar` (the Volume path) and `SETUP_PLATFORM=modal`. The engine binds `0.0.0.0` for every platform except Runpod, which is what Modal needs. `main.py`, `logic.py` and `models.py` need no change: `weights_root()` takes a local `MODEL` path, and the audio comes as a signed `https://storage.googleapis.com/` URL, as on Runpod.
- The image pull secret: reuse the read-only Artifact Registry service account of `infra/core` (the one behind the Runpod registry credential `gcp-models`). Put its key JSON in a Modal Secret with the key `SERVICE_ACCOUNT_JSON`.
- Slack: the engine posts "ready" and "scaled to 0" itself when `SLACK_BOT_TOKEN` and `SLACK_CHANNEL` are set. Put them in a Modal Secret.

### Q4. Weights

- Use a Modal Volume (`stt-a-weights`, Volumes v2). Volumes are "optimized for write-once, read-many" and "distributed by default ... without needing to manage replicas across regions". So there is no data center pin as with the Runpod network volumes. [8]
- Data on a Volume is stored in the United States. The weights are public model files, so this is not a problem. The audio is not stored on Modal. [8]
- Fill the Volume once with a one-shot Modal Function that copies the 3 Hugging Face repos (the `HF_REPO` values of the weights-copy runs in the STT-A README) into `asr/`, `aligner/` and `pyannote/`, at pinned revisions, with `HF_TOKEN` from a Modal Secret. The copy runs in the Modal cloud, not from the laptop (the laptop upload was about 0.18 MB/s for Runpod).
- Rejected: a download at each start (it adds minutes to every cold start and depends on Hugging Face). Possible but not needed: `modal.CloudBucketMount` of `gs://<project_id>-models` with `read_only=True` and `key_prefix`. It needs a GCS HMAC key as a Modal Secret, and it reads slower than a Volume for many small files. [11]

### Q5. HTTP and auth

- URL: `https://<workspace>--<label>.modal.run`. The label is ours (for example `stt-a-qwen3-asr-diar`), so the adapter knows the URL before the deploy. Custom domains need the Team plan; we do not need one. [12]
- Auth: `requires_proxy_auth=True` on the web server. A request without a token gets 401. The token goes in the `Modal-Key` and `Modal-Secret` headers, or as `Authorization: Bearer wk-<id>.ws-<secret>`. The Bearer form fits `auth_header()` in `cors_proxy.py` without a change: add `"modal": "MODAL_API_KEY"` to `KEYS` and a secret `modal-api-key` in `infra/core`. Make the token with `modal workspace proxy-tokens create`. [13] Measured: both header forms work, and a call without a token gets 401.
- Time limits: every Modal web endpoint (also `web_server`) stops an HTTP request after 150 s and sends HTTP 303 to a result URL. A client that follows the redirect gets the answer later (up to 20 redirects, about 50 min). The 303 "doesn't work with CORS requests", but our browser never calls Modal: the CORS proxy on Cloud Run does. [14]
- Our limits: the proxy waits 280 s (`COLD_WAIT`) for the answer headers, then answers 429 with `Retry-After: 30`. The gateway deadline is 300 s. A warm STT-A call on a short file takes about 8 s. A warm call on the 13 s test file took 3.1 s on Modal. A cold call took 157 to 169 s, so it always passes 150 s and gets the 303. A long file can pass 150 s too.
- Needed proxy change: for `auth == "modal"`, follow a 303 with a `GET` to the `Location` URL with the same auth header. Count the time of all redirects against `COLD_WAIT`, so the 429 rule stays the same. The Function `timeout` (default 300 s, max 24 h) must be above the longest GPU run; set 600 s, the STT-A limit "600 s of GPU time per request". [15]

### Q6. IaC

- There is no Terraform provider for Modal, official or community (Terraform Registry search on 2026-11-24). Deploy is the `modal deploy` CLI or the Python SDK. Auth: `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` (they win over `~/.modal.toml`), and `MODAL_ENVIRONMENT` picks the environment. [16][17]
- HCP Terraform remote runs cannot run `modal deploy`. So the split is the same as for Vertex AI (`scripts/platforms/vertex.py`):
  - Terraform: a `platform-modal` adapter with no resources. It only computes the common `target` output and a `modal` spec output (image, GPU list, env, port, idle seconds, Volume, secrets). `post_apply = "modal"` makes `scripts/deploy.py` call `scripts/platforms/modal.py`.
  - Post-apply: `scripts/platforms/modal.py` writes the spec to a JSON file and runs `modal deploy` on 1 shared app file (for example `scripts/platforms/modal_app.py`) that reads the JSON. `undeploy` runs `modal app stop`. `status` runs `modal app list`.
- The `modal` CLI is a pip package. `scripts/` is standard library only, so `modal.py` must run the CLI as a subprocess (for example `uvx modal deploy ...`), and the app file is Modal code, not a helper script. This is a small exception to the repo rule; the user must accept it.

Target output of the adapter:

```hcl
target = {
  id          = "modal"
  label       = "Modal"
  url         = "https://${var.options.workspace}--${local.label}.modal.run"
  append_path = true
  auth        = "modal"  # the proxy sends MODAL_API_KEY
  cold_start  = "wait"   # the request waits; the proxy follows the 303 of a slow answer
  deadline    = 300
  post_apply  = "modal"  # scripts/platforms/modal.py runs modal deploy
}
```

### Q7. Cost

Prices from the pricing page [1], checked against `modal billing rates` on 2026-11-25. Size of the spike: 4 physical cores (8 vCPU), 32 GiB memory. (Vertex AI uses 12 vCPU and 48 GB; ffmpeg decode and Pyannote clustering run on the CPU. The spike calls were fast with 4 cores.) Modal gave an A10G every time, so plan with the A10G price.

| Part | Price per second | Per hour |
|---|---|---|
| A10G (Modal type "A10") | $0.000306 | $1.10 |
| 4 cores × $0.0000131 | $0.0000524 | $0.19 |
| 32 GiB × $0.00000222 | $0.0000710 | $0.26 |
| **Total (A10G)** | **$0.000430** | **$1.55** |
| Total if Modal gives an L4 | $0.000345 | $1.24 |

Scenarios (A10G, no region pin):

| Use | Billed time | Cost |
|---|---|---|
| Idle at 0 containers | 0 | $0 |
| 1 single call, `scaledown_window = 300` (cold start about 150 s + 5 s work + 300 s idle) | about 455 s | about $0.20 |
| The same with `scaledown_window = 60` | about 215 s | about $0.09 |
| 1 call every few minutes for 1 hour (the container stays up) | about 65 min | about $1.68 |
| The spike (measured) | 4 cold starts, 2 warm calls, builds, Volume fill | $0.67 |

The $30 Starter credit per month covers about 19 hours of a running container. Volumes: the spike billed $0.02 for Volumes, and the free storage allowance covered it.

## Planned integration steps

1. **Spike: done on 2026-11-25** (see "Spike results"). The Volume `stt-a-weights` is filled. The spike files are removed; the shared app file `scripts/platforms/modal_app.py` replaces them.
2. **Secrets: done.** `.env.example` has `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `MODAL_PROFILE` (the workspace name) and `MODAL_API_KEY` (the proxy token). `infra/core` writes `MODAL_API_KEY` to the secret `modal-api-key` (`provider_keys.tf`, write-only) and has the sensitive output `registry_pull_key` (the read-only `runpod-pull` key). `scripts/platforms/modal.py` gives the pull key, `HF_TOKEN` and the Slack values to Modal at deploy time (no named Modal secrets).
3. **Adapter: done.** `infra/modules/platform-modal/` (outputs `target` and `modal`, no resource) with `terraform test`. The facade `infra/modules/model/` accepts `"modal"`, and the proxy gets `MODAL_API_KEY` from `modal-api-key`.
4. **Proxy: done.** `cors_proxy.py` sends `MODAL_API_KEY` for `auth = "modal"` and follows a 302 or 303 with a `GET` (at most 10 hops) within `COLD_WAIT`. Unit tests in `infra/modules/cors-proxy/tests/test_cors_proxy.py`.
5. **Post-apply: done.** `scripts/platforms/modal.py` (deploy, undeploy, status) runs the pinned modal CLI through `uvx` on `scripts/platforms/modal_app.py`. Tests: `scripts/tests/test_modal_platform.py`. Docs: `infra/README.md` (sections "Module: platform-modal" and "Modal setup (once)") and `docs/README.md`.
6. **STT-A: done in code.** `platforms = ["modal", "vertex", "runpod"]` (Modal is the default), `platform_options.modal`, the output `modal` and the variable `modal_workspace`. The user still has to make the proxy token, sync, apply `infra/core` and STT-A, and run `./scripts/deploy.py deploy deployments/stt-a-qwen3-asr-diar --platform modal` (see the STT-A README, section "Deploy").
7. **Later:** decide if LLM-B moves to Modal too, and if the parked Runpod endpoint of STT-A is removed.

## Sources

- [1] https://modal.com/pricing
- [2] https://modal.com/docs/guide/gpu
- [3] https://modal.com/docs/guide/region-selection
- [4] https://serverlessgpubench.com/ (September 2026) and https://modal.com/resources/best-serverless-gpu-providers (Modal's own article, no numbers)
- [5] https://modal.com/docs/guide/scale
- [6] https://modal.com/docs/guide/cold-start
- [7] https://modal.com/docs/guide/memory-snapshot
- [8] https://modal.com/docs/guide/volumes
- [9] https://modal.com/docs/guide/existing-images and `Image.from_registry` in https://modal.com/llms-full.txt
- [10] https://modal.com/docs/guide/servers
- [11] https://modal.com/docs/guide/cloud-bucket-mounts
- [12] https://modal.com/docs/guide/webhook-urls
- [13] https://modal.com/docs/guide/webhook-proxy-auth
- [14] https://modal.com/docs/guide/webhook-timeouts
- [15] https://modal.com/docs/guide/timeouts
- [16] https://modal.com/docs/guide/continuous-deployment
- [17] https://modal.com/docs/guide/environments
