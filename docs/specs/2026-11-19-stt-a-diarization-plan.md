# STT-A Qwen3-ASR with diarization: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Vertex AI container that runs Qwen3-ASR-1.7B, Qwen3-ForcedAligner-0.6B and Pyannote community-1 behind the Gemini 3.5 Transcribe contract, plus a CPU upload URL service, the Terraform, Slack alerts and a UI tab.

**Architecture:** Pure logic (`app/logic.py`, stdlib only) holds the rules of the spec and has unit tests. `app/main.py` connects the 3 models to the logic behind FastAPI, with the LLM-B start pattern. The upload service is 1 stdlib file that runs in the stock Python image, as the CORS proxy does. Terraform copies LLM-B (`vertex-model`, CORS proxy, API Gateway, `alerts.tf`). The agent writes code and runs offline checks. The user builds the image, applies and deploys.

**Tech Stack:** Python 3.12, FastAPI, `qwen-asr[vllm]`, `pyannote.audio` 4.x, Terraform `google` / `google-beta` `~> 8.10`, React + Vite (`ui/`).

**Spec:** `docs/specs/2026-11-19-stt-a-diarization-design.md` (merged into `docs/specs/2026-11-21-stt-a-design.md` on 2026-11-21)

## Global Constraints

- Folder `deployments/stt-a-qwen3-asr-diar/`. Gateway ID `stt-a-qwen3-asr-diar`. Image `${var.region}-docker.pkg.dev/${var.project_id}/models/stt-a-qwen3-asr-diar:${var.image_tag}`, default tag `0.1.0`.
- Routes: `POST /v1beta/interactions` (GPU container), `POST /v1beta/uploads` (upload service). Health `GET /health`. Port `$AIP_HTTP_PORT` (8080). 1 Uvicorn worker, 1 request at a time.
- Max audio 1800 s. Max inline audio 20 MB decoded. Turn split at 300 s. Merge gap 1.0 s. Drop turns under 0.2 s. `max_speakers=8`. Language detection 1 time on the longest turn, cut to 30 s.
- Labels `spk_1`, `spk_2` ... in the order of first speech. Offsets `f"{sec:.3f}s"`.
- The 30 languages and the code map: copy the spec section "Language table" exactly. Aligner languages: Chinese, English, Cantonese, French, German, Italian, Japanese, Korean, Portuguese, Russian, Spanish.
- Error body: `{"error": {"code": <http code>, "message": <text>, "status": "INVALID_ARGUMENT"}}` for 400, `"INTERNAL"` for 500.
- `gs://` input only from bucket `<project_id>-stt-audio` (env `AUDIO_BUCKET`). Never fetch `http(s)://` audio.
- Upload: `size_bytes` 1 to 500 000 000, audio MIME types from the spec, V4 signed `PUT`, 900 s, object `uploads/<uuid4>`.
- Slack ready line: `models ready`, printed after all 3 models load.
- `app/logic.py` and `upload/upload.py` import only the standard library.
- Min replicas 0. No public endpoint. The agent never runs apply, deploy, Cloud Build or a real call (`CLAUDE.md`). Scripts run directly, never with `direnv exec`.
- Docs prose in Simplified Technical English.

## Review Focus

1. Silence, or 0 Pyannote turns: HTTP 200 with `output_text == ""` and no annotations, not a crash. Test `test_no_turns` (Task 2).
2. A turn where ASR returns empty text: no words, and no aligner call for that turn. Tests `test_empty_turn_text` (Task 2), `test_empty_text_skips_aligner` (Task 3).
3. The aligner raises an error or returns 0 items: estimated word times, not HTTP 500. Test `test_aligner_failure_falls_back` (Task 3).
4. A request while the models still load: HTTP 503 from `/v1beta/interactions` and `/health`, not a hang or a 500. Test `test_not_ready_503` (Task 3).
5. An upload request for 0 bytes, 500 000 001 bytes or `video/mp4`: HTTP 400 with the error shape, and no signed URL. Test `test_upload_rejects` (Task 5).

---

### Task 1: Pin the versions and close the open facts

**Files:**
- Create: `deployments/stt-a-qwen3-asr-diar/image/requirements.txt`
- Modify: `docs/specs/2026-11-19-stt-a-diarization-design.md` (section "Constraints and facts checked")

**Interfaces:**
- Produces: the base image tag and the pinned packages for Task 4.

- [ ] **Step 1:** In a new empty folder, run `pip download "qwen-asr[vllm]==0.0.6" --no-deps -d .` and read `METADATA` in the wheel. Write down the `vllm` and `transformers` requirements.
- [ ] **Step 2:** If `vllm==0.33.0` meets them, keep `FROM vllm/vllm-openai:v0.33.0` (as LLM-B). If not, pick the newest `vllm/vllm-openai` release tag that meets them, and put the reason in a comment at the top of `requirements.txt`.
- [ ] **Step 3:** Pin exact versions in `requirements.txt`: `qwen-asr` (without the `[vllm]` extra: vLLM comes from the base image), `pyannote.audio` (latest 4.x), `soundfile`, `google-cloud-storage`. Do not pin `torch`, `vllm`, `fastapi`, `uvicorn` (the base image has them).
- [ ] **Step 4:** Check with context7 or the package source: the Pyannote call that loads a local pipeline folder offline, the name `exclusive_speaker_diarization`, and the unit of `start_time` in `qwen-asr` (seconds expected). Write the 3 facts into the spec.
- [ ] **Step 5:** Commit: `git commit -m "chore: pin STT-A image versions"`.

### Task 2: Pure logic with unit tests

**Files:**
- Create: `deployments/stt-a-qwen3-asr-diar/image/app/__init__.py` (empty), `image/app/logic.py`
- Test: `deployments/stt-a-qwen3-asr-diar/image/tests/test_logic.py`

**Interfaces:**
- Produces (in `app/logic.py`):
  - `LANGS: dict[str, str]` (lower-case code to Qwen name: 30 names plus the aliases `tl`, `zh-hk`, `zh-yue`), `ALIGNER_LANGS: frozenset[str]`
  - `class BadRequest(Exception)`
  - `@dataclass Job: data: bytes | None; gcs_uri: str | None; language: str | None; diarize: bool; words: bool`
  - `parse_request(body: dict, audio_bucket: str, max_bytes: int = 20_000_000) -> Job`
  - `check_duration(seconds: float, limit: float = 1800.0) -> None`
  - `@dataclass Turn: start: float; end: float; speaker: str | None`
  - `make_turns(segments: list[tuple[float, float, str]], total: float, diarize: bool) -> list[Turn]`
  - `longest_clip(turns: list[Turn], max_len: float = 30.0) -> tuple[float, float]`
  - `@dataclass Word: text: str; start: float; end: float`
  - `estimate_words(text: str, start: float, end: float) -> list[Word]`
  - `label_speakers(turns: list[Turn]) -> dict[str, str]`
  - `fmt_offset(seconds: float) -> str`
  - `build_response(turns: list[Turn], texts: list[str], words: list[list[Word]], labels: dict[str, str], job: Job) -> dict`
  - `error_body(message: str, code: int = 400) -> dict`

- [ ] **Step 1: Write the failing tests** (`unittest`, stdlib only):
  - `test_language_codes`: `len(set(LANGS.values())) == 30`. `language_codes` `["pt-BR"]` gives `"Portuguese"`, `["zh-HK"]` `"Cantonese"`, `["EN"]` `"English"`, `["fil"]` and `["tl"]` `"Filipino"`. `["xx"]` raises `BadRequest`. `["en", "de"]` and `[]` give `None`. `len(ALIGNER_LANGS) == 11` and `ALIGNER_LANGS <= set(LANGS.values())`.
  - `test_request_forms`: `{"type": "audio", "data": <b64>, "mime_type": "audio/wav"}` gives `data`. `{"type": "audio", "uri": "gs://B/x.wav"}` and `{"type": "file", "file_uri": "gs://B/x.wav"}` with `audio_bucket="B"` give `gcs_uri`. These raise `BadRequest`: `gs://other/x.wav`, `https://a/b.wav`, 0 items, 2 items, bad base64, data over `max_bytes`.
  - `test_modes`: no `transcription_config` gives `diarize=False, words=False`. `mode="smart"` with `diarization_mode` raises. `{"type": "smart"}` alone passes. `{"type": "verbatim", "diarization_mode": "speaker", "timestamp_granularities": ["word"]}` gives both `True`. `custom_vocabulary` present raises.
  - `test_duration_limit`: `check_duration(1800.0)` passes, `check_duration(1800.1)` raises.
  - `test_make_turns`: segments `[(0,2,"A"),(2.5,4,"A"),(6,7,"B"),(7.05,7.2,"A")]`, total 8, diarize: `[Turn(0,4,"A"), Turn(6,7,"B")]`. A 700 s turn gives 3 turns of 233.333 s (round to 3 decimals). `diarize=False`, total 650: 3 turns of 216.667 s with `speaker=None`.
  - `test_no_turns`: `make_turns([], 5.0, True) == []`, and `build_response([], [], [], {}, job)` has `output_text == ""` and no `annotations` key.
  - `test_longest_clip`: turns of 10 s and 50 s (start 20) give `(20, 50)`.
  - `test_estimate_words`: `estimate_words("ab abcd", 1.0, 2.2) == [Word("ab", 1.0, 1.4), Word("abcd", 1.4, 2.2)]` (round to 3 decimals). `estimate_words("   ", 0, 1) == []`.
  - `test_empty_turn_text`: a turn with text `""` adds no line to `output_text` and no words.
  - `test_labels`: first speech order `"B","A","B"` gives `{"B": "spk_1", "A": "spk_2"}`.
  - `test_response_shape`: 2 turns, `diarize=True`: `output_text == "Hello there.\nHi."`, `steps[0]["type"] == "model_output"`, `content[0]["type"] == "text"`, `status == "completed"`, first annotation `== {"type": "word_info", "text": "Hello", "speaker": "spk_1", "start_offset": "0.100s", "end_offset": "0.400s"}`. `diarize=False, words=True`: no `speaker` key. Both `False`: no `annotations` key.
  - `test_error_body`: `error_body("x") == {"error": {"code": 400, "message": "x", "status": "INVALID_ARGUMENT"}}`; `error_body("x", 500)["error"]["status"] == "INTERNAL"`.
- [ ] **Step 2:** Run `cd deployments/stt-a-qwen3-asr-diar/image && python3 -m unittest tests.test_logic -v`. Expected: FAIL (`ModuleNotFoundError: app.logic`).
- [ ] **Step 3:** Implement `app/logic.py`. Order in `make_turns`: drop short segments, merge, split. Language match: lower case, the full code first, then the primary subtag.
- [ ] **Step 4:** Run the tests again. Expected: all PASS.
- [ ] **Step 5:** Commit: `git commit -m "feat: STT-A transcription logic with unit tests"`.

### Task 3: FastAPI app with injected models

**Files:**
- Create: `deployments/stt-a-qwen3-asr-diar/image/app/main.py`, `image/app/models.py`
- Test: `deployments/stt-a-qwen3-asr-diar/image/tests/test_main.py`

**Interfaces:**
- Consumes: all of Task 2.
- Produces:
  - `class Models(Protocol)`: `diarize(audio: np.ndarray, sr: int) -> list[tuple[float, float, str]]`; `transcribe(clips: list[np.ndarray], sr: int, language: str | None) -> list[tuple[str, str]]` (text, language name); `align(clip: np.ndarray, sr: int, text: str, language: str) -> list[Word]` (times from the clip start); `read_gcs(uri: str) -> bytes`.
  - `create_app(load: Callable[[], Models], audio_bucket: str) -> FastAPI`. The app calls `load` in a thread at start (`asyncio.to_thread`). Until it returns, `/health` and `/v1beta/interactions` return 503. After it returns, the app prints `models ready` (flush) and `/health` returns 200.
  - `decode(data: bytes) -> tuple[np.ndarray, int]`: ffmpeg pipe to 16 kHz mono float32.
  - Module entry: `python3 -m app.main` runs uvicorn on `0.0.0.0:$AIP_HTTP_PORT`, 1 worker, with `load = RealModels` from `app/models.py`.

- [ ] **Step 1: Write the failing tests** with `fastapi.testclient.TestClient`, a `FakeModels` class (fixed turns and texts, records calls), and `decode` patched to return 10 s of zeros:
  - `test_not_ready_503`: with a `load` that blocks on an `Event`, `/health` and `POST /v1beta/interactions` return 503.
  - `test_ready_prints_line`: after `load` returns, `/health` is 200 and stdout has `models ready`.
  - `test_transcribe_two_speakers`: a valid request gives 200 and 2 distinct `speaker` values.
  - `test_language_detected_once`: without `language_codes`, `transcribe` runs 1 time with `language=None` on 1 clip of 30 s or less, then 1 time with the detected language for all turns.
  - `test_non_aligner_language_estimates`: detected `"Thai"`: `align` is never called, and every word is inside its turn.
  - `test_empty_text_skips_aligner`: a turn text `""` gets no `align` call.
  - `test_aligner_failure_falls_back`: `align` raises `RuntimeError`: HTTP 200, estimated word times.
  - `test_bad_request`: `mode="smart"` with diarization gives 400 with `error_body`.
- [ ] **Step 2:** Run `cd deployments/stt-a-qwen3-asr-diar/image && uv run --with fastapi --with httpx --with numpy python -m unittest tests.test_main -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `app/main.py`. Model calls run in `asyncio.to_thread` under 1 `asyncio.Lock`. Add the turn start to aligner times. `BadRequest` gives 400. Any other error gives 500 with `error_body(..., 500)`.
- [ ] **Step 4:** Implement `app/models.py` (`RealModels`, no unit test): copy `$AIP_STORAGE_URI` to `/models` with `google-cloud-storage`; `Qwen3ASRModel.LLM(model="/models/asr", gpu_memory_utilization=0.5, max_new_tokens=4096)`; `Qwen3ForcedAligner.from_pretrained("/models/aligner", dtype=torch.bfloat16, device_map="cuda:0")`; the Pyannote pipeline from `/models/pyannote` on `cuda`, called with `max_speakers=8`, reading `exclusive_speaker_diarization`. `read_gcs` uses `google-cloud-storage`.
- [ ] **Step 5:** Run the tests of Task 2 and Task 3. Expected: all PASS.
- [ ] **Step 6:** Commit: `git commit -m "feat: STT-A FastAPI app"`.

### Task 4: Image build files

**Files:**
- Create: `deployments/stt-a-qwen3-asr-diar/image/Dockerfile`, `image/cloudbuild.yaml`, `image/.dockerignore`

**Interfaces:**
- Consumes: the base tag and `requirements.txt` from Task 1; `python3 -m app.main` from Task 3.

- [ ] **Step 1:** `Dockerfile`: `FROM` the Task 1 tag, `apt-get install ffmpeg`, `pip install -r requirements.txt`, copy `app/`, `ENV HF_HUB_OFFLINE=1`, `ENTRYPOINT ["python3", "-m", "app.main"]` (it replaces the vLLM entrypoint). `.dockerignore` excludes `tests/`.
- [ ] **Step 2:** `cloudbuild.yaml`: copy `deployments/llm-b-qwen35-9b-fastapi/image/cloudbuild.yaml`. Change the image name to `stt-a-qwen3-asr-diar` and `_TAG` to `0.1.0`. Fix the comment with the `gcloud builds submit` line for this folder.
- [ ] **Step 3:** If Docker is installed, run `docker build --check deployments/stt-a-qwen3-asr-diar/image` (lint only). Expected: no errors. Otherwise, say that the check was skipped.
- [ ] **Step 4:** Commit: `git commit -m "feat: STT-A image build files"`.

### Task 5: Upload URL service

**Files:**
- Create: `deployments/stt-a-qwen3-asr-diar/upload/upload.py`
- Test: `deployments/stt-a-qwen3-asr-diar/upload/test_upload.py`

**Interfaces:**
- Produces:
  - `AUDIO_TYPES: frozenset[str]` (`audio/wav`, `audio/mp3`, `audio/aiff`, `audio/aac`, `audio/ogg`, `audio/flac`, `audio/mpeg`, `audio/m4a`, `audio/l16`, `audio/opus`, `audio/alaw`, `audio/mulaw`, `audio/webm`)
  - `check_request(body: dict) -> tuple[str, int]` (mime type, size); raises `ValueError` with the message for the 400.
  - `signed_put(bucket: str, name: str, mime: str, size: int, sa_email: str, now: datetime, sign: Callable[[bytes], bytes]) -> str`: a V4 signed URL (`GOOG4-RSA-SHA256`, `X-Goog-Expires=900`, signed headers `content-type;host;x-goog-content-length-range`).
  - `answer(bucket: str, name: str, mime: str, size: int, url: str) -> dict`: the spec answer (`upload_url`, `method`, `headers`, `file_uri`, `expires_in`).
  - The server: `ThreadingHTTPServer` on `$PORT`. `OPTIONS` gives 204 with CORS headers. `POST /v1beta/uploads` gives 200 or 400, always with CORS headers. `sign` calls the IAM Credentials `signBlob` API with a metadata server token (stdlib `urllib`).
  - Env: `AUDIO_BUCKET`, `SA_EMAIL`.

- [ ] **Step 1: Write the failing tests** (`unittest`, stdlib only):
  - `test_upload_rejects`: `size_bytes` 0, 500 000 001, a string, and `mime_type` `video/mp4` raise `ValueError`.
  - `test_check_ok`: `{"mime_type": "audio/mpeg", "size_bytes": 123}` gives `("audio/mpeg", 123)`.
  - `test_signed_url_shape`: with a fixed `now` and `sign=lambda b: b"x"`, the URL starts with `https://storage.googleapis.com/B/uploads/`, has `X-Goog-Algorithm=GOOG4-RSA-SHA256`, `X-Goog-Expires=900`, `X-Goog-SignedHeaders=content-type%3Bhost%3Bx-goog-content-length-range` and `X-Goog-Signature=78`.
  - `test_string_to_sign`: the bytes given to `sign` start with `GOOG4-RSA-SHA256\n<YYYYMMDDTHHMMSSZ>\n<YYYYMMDD>/auto/storage/goog4_request\n`.
  - `test_answer`: `file_uri == "gs://B/uploads/n"`, `headers == {"Content-Type": "audio/mpeg", "x-goog-content-length-range": "0,123"}`, `expires_in == 900`, `method == "PUT"`.
- [ ] **Step 2:** Run `cd deployments/stt-a-qwen3-asr-diar/upload && python3 -m unittest test_upload -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `upload.py`. Follow the GCS V4 signing steps (canonical request, then string to sign, then hex of the signature). Copy the CORS header set and the server structure from `infra/modules/cors-proxy/cors_proxy.py`.
- [ ] **Step 4:** Run the tests again. Expected: all PASS.
- [ ] **Step 5:** Commit: `git commit -m "feat: STT-A upload URL service"`.

### Task 6: Core: audio bucket and gateway API

**Files:**
- Modify: `infra/core/main.tf` (new bucket next to `google_storage_bucket.models`), `infra/core/gateways.tf` (`local.gateway_apis`), `infra/core/outputs.tf`
- Test: `infra/core/tests/core.tftest.hcl`, `infra/core/tests/gateways.tftest.hcl`

**Interfaces:**
- Produces: bucket `${var.project_id}-stt-audio`, output `stt_audio_bucket`, gateway API `stt-a-qwen3-asr-diar`.

- [ ] **Step 1: Write the failing tests.** In `core.tftest.hcl`, run `stt_audio_bucket`: name `"p-stt-audio"` (the test project ID), location `var.region`, `uniform_bucket_level_access == true`, `force_destroy == true`, 1 lifecycle rule with `age == 1` and action `Delete`, 1 CORS rule with `method == ["PUT"]`, `origin == ["*"]`, `response_header` that holds `Content-Type` and `x-goog-content-length-range`. In `gateways.tftest.hcl`, assert that `local.gateway_apis` contains `"stt-a-qwen3-asr-diar"`.
- [ ] **Step 2:** Run `cd infra/core && terraform init -backend=false && terraform test`. Expected: FAIL.
- [ ] **Step 3:** Add the bucket (copy the settings of `google_storage_bucket.models`), the output and the gateway ID.
- [ ] **Step 4:** Run `./scripts/check.py infra/core`. Expected: all `ok`.
- [ ] **Step 5:** Commit: `git commit -m "feat: core audio bucket and STT-A gateway API"`.

### Task 7: Deployment Terraform

**Files:**
- Create in `deployments/stt-a-qwen3-asr-diar/`: `main.tf`, `backend.tf`, `variables.tf`, `outputs.tf`, `gateway.tf`, `cors_proxy.tf`, `upload.tf`, `alerts.tf`
- Test: `tests/deployment.tftest.hcl`, `tests/gateway.tftest.hcl`, `tests/alerts.tftest.hcl`, `tests/upload.tftest.hcl`

**Interfaces:**
- Consumes: the bucket name from Task 6 (built from `var.project_id`, no remote state); `upload/upload.py` from Task 5.
- Produces: outputs `endpoint_id`, `endpoint_dns`, `vertex`, `gateway_url`, `gateway_id`, `gateway_region`, `api_config`, `ui`.

- [ ] **Step 1: Write the failing tests** (copy the LLM-B tests and change the values):
  - `deployment.tftest.hcl`: `imageUri == "us-central1-docker.pkg.dev/p/models/stt-a-qwen3-asr-diar:0.1.0"`, `predictRoute == "/v1beta/interactions"`, `artifactUri == "gs://p-models/stt-a-qwen3-asr-diar/"`, `minReplicaCount == 0`, env `AUDIO_BUCKET == "p-stt-audio"`, 1 `google_storage_bucket_iam_member` with role `roles/storage.objectViewer` on `p-stt-audio` for the model SA.
  - `gateway.tftest.hcl`: path `/v1beta/interactions` has `post` and `options` (`security = []`), its backend is the CORS proxy, deadline 300. Path `/v1beta/uploads` has `post` and `options`, its own `x-google-backend` is the upload service URL, deadline 30.
  - `alerts.tftest.hcl`: the filters hold the endpoint ID, `models ready` and `Application shutdown complete.`.
  - `upload.tftest.hcl`: the upload service has `min_instance_count == 0`, no GPU, env `AUDIO_BUCKET` and `SA_EMAIL`; its SA has `roles/storage.objectCreator` on `p-stt-audio` and `roles/iam.serviceAccountTokenCreator` on itself; the gateway SA has `roles/run.invoker` on it.
- [ ] **Step 2:** Run `cd deployments/stt-a-qwen3-asr-diar && terraform init -backend=false && terraform test`. Expected: FAIL.
- [ ] **Step 3:** Write the files. `main.tf`, `variables.tf`, `backend.tf` (workspace `stt-a-qwen3-asr-diar-vertex`), `alerts.tf`, `cors_proxy.tf`: copy LLM-B and apply the spec section "Terraform" (`predict_route` instead of `invoke_routes`, `:rawPredict` target as LLM-A, `machine_type = "g2-standard-12"`). `upload.tf`: call `infra/modules/model-service` the way `infra/modules/cors-proxy/main.tf` does (stock `python:3.13.9-slim` through the `dockerhub` proxy, `command = ["python3"]`, `args = ["-u", "-c", file("${path.module}/upload/upload.py")]`, `cpu = "1"`, `memory = "256Mi"`, `invokers = []`), plus the 3 IAM members. Note: the spec said "own `google_cloud_run_v2_service`"; the module gives the same result with less code and follows the CORS proxy. `outputs.tf`: LLM-B outputs plus `ui` with `type = "stt"`, `title = "STT-A Qwen3 ASR + speakers"`, `model = "qwen3-asr-diar"`, `features = { cold_start = "vertex-429", max_mb = 20 }`.
- [ ] **Step 4:** Run `./scripts/check.py deployments/stt-a-qwen3-asr-diar`. Expected: all `ok`, including `scale alerts`.
- [ ] **Step 5:** Commit: `git commit -m "feat: STT-A diarization deployment on Vertex AI"`.

### Task 8: UI tab, mock, checks and docs

**Files:**
- Create: `ui/src/panels/Stt.tsx`, `deployments/stt-a-qwen3-asr-diar/README.md`
- Modify: `ui/src/panels/index.ts`, `ui/mock-server.mjs`, `ui/public/models.mock.json`, `ui/src/lib.test.ts`, `.claude/skills/model-ui/SKILL.md` (features table, `stt` keys), `scripts/check.py`, `infra/README.md`, `docs/README.md`, `docs/backends.md`, `docs/research/03-speech-models.md` (STT-A row points to this deployment)

**Interfaces:**
- Consumes: `call()`, `curlFor()` from `ui/src/api.ts`; `Timings`, `Status`, `Curl` from `ui/src/components.tsx`; the response shape from Task 2; the upload answer from Task 5.
- Produces: `groupTurns(annotations: WordInfo[]): {speaker: string; text: string; start: string}[]`, exported from `Stt.tsx` for the test.

- [ ] **Step 1: Write the failing test** in `ui/src/lib.test.ts`: `groupTurns` joins words of 1 speaker in a row, starts a new group when the speaker changes, and keeps the `start_offset` of the first word. Run `cd ui && npm test`. Expected: FAIL.
- [ ] **Step 2:** Implement `Stt.tsx` (follow the `model-ui` skill, "new model type"): file input, language select (auto plus the 30 codes), diarization check box (on by default). A file of 20 MB or less goes as inline base64. A larger file goes through `/v1beta/uploads`, the signed `PUT`, then `file_uri`. Show 1 group per turn with 1 color per speaker, and the curl. Add `stt: Stt` to `PANELS`. In the mock, add `POST /v1beta/uploads` (answer with a `upload_url` on the mock itself, which accepts the `PUT`) and `POST /v1beta/interactions` (a fixed 2-speaker answer in the Task 2 shape). Add the tab to `models.mock.json`.
- [ ] **Step 3:** Run `cd ui && npm test && npm run build`. Expected: PASS. Then use the `verify-ui` skill against the mock (small file and a file over 20 MB) and keep the screenshot.
- [ ] **Step 4:** `scripts/check.py`: for each `deployments/*/image/tests/` and `deployments/*/upload/`, run `python3 -m unittest` (stdlib tests only). Skip `test_main` with a note when `fastapi` cannot be imported.
- [ ] **Step 5:** Write the deployment README with real values: `./scripts/preflight.py --weights stt-a-qwen3-asr-diar --l4`; the Hugging Face gate for Pyannote; the 3 weights-copy runs (spec table); `gcloud builds submit` for the image; apply core, then the deployment; `./scripts/vertex.py deploy deployments/stt-a-qwen3-asr-diar`; `./scripts/ui-deploy.py --config-only`; a test `curl` with inline base64 and 1 with an upload; the Slack check (`models ready` in the logs, both messages arrive); the user checks (GPU memory of the 3 models, a real Gemini answer if available); fields for the real-time factor and the cold start; destroy. Add the deployment to `infra/README.md`, `docs/README.md` and `docs/backends.md` (links, no repeated commands).
- [ ] **Step 6:** Run `./scripts/check.py`. Expected: all `ok`.
- [ ] **Step 7:** Commit: `git commit -m "feat: STT tab in the test UI and STT-A docs"`.
