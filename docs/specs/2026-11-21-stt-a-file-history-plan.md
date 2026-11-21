# STT-A stored files and transcript history: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every uploaded STT-A audio file and every transcript run in the audio bucket, with a CPU files service (list, history, transcribe again) and a UI to browse and compare versions.

**Architecture:** The upload service (`deployments/stt-a-qwen3-asr-diar-vertex/upload/upload.py`) becomes the files service. It stays 1 stdlib file, because it runs as `python3 -c <file>`. A pure `route(method, path, body, store, gpu, cfg, now)` function holds all route logic, so tests call it with a fake store and a fake GPU. The HTTP handler only parses and writes. The GPU service does not change. Terraform renames the service, adds IAM and 4 gateway paths. The UI STT panel is rebuilt around the files list.

**Tech Stack:** Python 3.13 stdlib (`urllib`, `http.server`), GCS JSON API, Terraform `google` / `google-beta` `~> 8.10`, React + Vite + vitest.

**Spec:** `docs/specs/2026-11-21-stt-a-design.md` (sections "Bucket layout", "Version JSON", "Files service", "Long files", "Terraform", "Test UI", "Security", "Done when").

## Global Constraints

- Bucket prefix `files/<id>/`: `audio`, `meta.json`, `versions/<version_id>.json`. `<id>` is UUID4. `<version_id>` is `YYYYMMDDTHHMMSSZ-xxxx` (4 lowercase hex).
- Routes: `POST /v1beta/uploads`, `GET /v1beta/files`, `GET /v1beta/files/{id}`, `GET /v1beta/files/{id}/versions/{version_id}`, `POST /v1beta/files/{id}/transcribe`.
- `name` 1 to 200 chars; `label` 0 to 200 chars; `size_bytes` 1 to 500 000 000; signed URL 900 s.
- A GPU `429` or any non-200 is returned as is, and nothing is saved. Only a GPU `200` writes a version, before the answer.
- Files service: name `stt-a-qwen3-asr-diar-files`, timeout `3600s`, env `AUDIO_BUCKET`, `SA_EMAIL`, `IMAGE_TAG`, `TARGET`. IAM: `objectCreator` + `objectViewer` on the audio bucket, `serviceAccountTokenCreator` on itself, `aiplatform.user` on the project.
- Gateway: operation-level `x-google-backend` with `APPEND_PATH_TO_ADDRESS` on every files-service operation (also `options`). Deadline 300 s for `transcribe`, 30 s for the others.
- Bucket: no lifecycle rule, `force_destroy = false`.
- `upload.py` imports only the standard library and stays 1 file.
- The agent never runs apply, deploy or a real call. Docs prose in Simplified Technical English.

## Review Focus

1. A path value that is not a UUID4 or a version id (`..`, `%2F`, `files/x`): HTTP 400 before any store call. Test `test_bad_ids_touch_no_store` (Task 2).
2. A file whose `PUT` never came (only `meta.json`): not in `GET /v1beta/files`, and `transcribe` gives 404. Tests `test_list_skips_files_without_audio`, `test_transcribe_missing_file` (Task 2).
3. GPU 429 (cold start) and GPU 500: the same status goes back, and no version is written. Test `test_gpu_errors_save_nothing` (Task 2).
4. More than 1 000 objects: the list follows `nextPageToken`. Test `test_gcs_list_follows_pages` (Task 2).
5. A link `#/stt-mock/<file id>` opens the STT tab with that file, and a plain `#/stt-mock` still works. Test `parseHash` in `ui/src/lib.test.ts` (Task 4).

---

### Task 1: Check the 2 open limits

**Files:**
- Modify: `docs/specs/2026-11-21-stt-a-design.md` (section "Constraints and facts checked")

**Interfaces:**
- Produces: the Vertex AI inference timeout value (and the Terraform field, if any) for Task 3; the container argument size limit for Task 2.

- [ ] **Step 1:** With context7 or the official docs, find the request timeout of a Vertex AI dedicated endpoint (`:rawPredict`) and how to raise it (for example `clientConnectionConfig.inferenceTimeout` on the endpoint, and whether `google_vertex_ai_endpoint` or `scripts/vertex.py` sets it).
- [ ] **Step 2:** Find the size limit of Cloud Run container `args`. Measure `wc -c upload/upload.py` now, and plan for about 3 times that size.
- [ ] **Step 3:** Write both facts as items 10 and 11 in the spec. If the endpoint timeout is below 3600 s and can be raised, Task 3 sets it to 3600 s. If it cannot, write the real limit in the spec "Long files" section. If the argument limit is below 3 times the file size, Task 3 builds a small image instead (write that in the spec).
- [ ] **Step 4:** Commit: `git commit -m "docs: STT-A endpoint timeout and container arg limit"`.

### Task 2: Files service logic and routes

**Files:**
- Modify: `deployments/stt-a-qwen3-asr-diar-vertex/upload/upload.py`
- Test: `deployments/stt-a-qwen3-asr-diar-vertex/upload/test_upload.py`

**Interfaces:**
- Consumes: the existing `AUDIO_TYPES`, `signed_put`, `error`, `sign_blob`, `token`, `CORS`.
- Produces (all in `upload.py`):
  - `ID_RE`, `VERSION_RE` (compiled regex, full match).
  - `check_request(body: dict) -> tuple[str, str, int]` (name, mime, size); raises `ValueError`.
  - `answer(bucket, file_id, mime, size, url) -> dict`: adds `"id"`; `file_uri` is `gs://<bucket>/files/<id>/audio`.
  - `new_version_id(now: datetime, rand: str) -> str`.
  - `gpu_request(file_uri: str, body: dict) -> tuple[dict, dict]`: (GPU body, settings); raises `ValueError` for a bad `language_codes` (not a list of strings), `diarization` (not a bool) or `label` (not a string, or over 200 chars).
  - `summary(version: dict) -> dict`.
  - `list_files(objects: list[dict]) -> list[dict]` from GCS list items (`name`, `size`, `timeCreated`, `metadata`).
  - `class Store` with `list(prefix) -> list[dict]`, `read(name) -> bytes`, `write(name, data, content_type, metadata=None) -> None`; `GcsStore(bucket)` implements it with the JSON API and `token()`, and follows `nextPageToken`.
  - `gpu_post(target: str, body: dict) -> tuple[int, bytes]` (urllib, access token, timeout 3600).
  - `route(method, path, body, store, gpu, cfg, now) -> tuple[int, dict]`. `cfg` is a dict with `bucket`, `sa_email`, `image_tag`, `target`, `sign`. `gpu` has the signature of `gpu_post`. `now` is a callable that returns a UTC `datetime`.

- [ ] **Step 1: Write the failing tests.** Use a `FakeStore` (a dict of name to `(bytes, metadata, timeCreated)`, records every call) and a `FakeGpu` (returns a fixed `(status, bytes)`, records calls):
  - `test_upload_rejects`: the existing cases, plus a missing `name`, `name` of 201 chars, and `name` not a string.
  - `test_check_ok`: `{"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 123}` gives `("a.mp3", "audio/mpeg", 123)`.
  - `test_answer`: `answer("B", "<id>", "audio/mpeg", 123, "https://u")["file_uri"] == "gs://B/files/<id>/audio"` and has `"id": "<id>"`.
  - `test_upload_route_writes_meta`: `route("POST", "/v1beta/uploads", {...}, ...)` gives 200; the store has `files/<id>/meta.json` with metadata `{"name": "a.mp3", "created": "2026-11-21T10:45:12Z"}`; `upload_url` path is `/B/files/<id>/audio`.
  - `test_version_id`: `new_version_id(datetime(2026, 11, 21, 10, 45, 12, tzinfo=timezone.utc), "3fa1") == "20261121T104512Z-3fa1"` and it matches `VERSION_RE`.
  - `test_gpu_request`: `{}` gives a body with `"mode": {"type": "verbatim", "timestamp_granularities": ["word"]}`, no `language_codes`, and settings `{"language_codes": [], "diarization": False}`. `{"language_codes": ["en"], "diarization": True}` adds `"diarization_mode": "speaker"` and `"language_codes": ["en"]`. `{"language_codes": "en"}`, `{"diarization": "yes"}`, `{"label": "x" * 201}` raise `ValueError`.
  - `test_list_skips_files_without_audio`: 2 files with `meta.json`, only 1 with `audio`, 2 versions on it: `GET /v1beta/files` gives 1 file with `versions == 2`, `latest` = the newer id, `size_bytes` from the `audio` object, `name` from the metadata.
  - `test_file_versions`: `GET /v1beta/files/<id>` gives the meta and the versions newest first; each summary has no `response` key, and has `text_chars` (length of `response.output_text`) and `speakers` (count of distinct `speaker` in the annotations).
  - `test_read_version`: `GET /v1beta/files/<id>/versions/<vid>` returns the stored JSON; an unknown `<vid>` gives 404.
  - `test_transcribe_saves_version`: GPU 200 with a Gemini answer; `POST /v1beta/files/<id>/transcribe` with `{"label": "t1"}` gives 201; the store has `files/<id>/versions/<vid>.json` with `image_tag`, `label == "t1"`, `settings`, `run_seconds`, `response`; the GPU got `file_uri == "gs://B/files/<id>/audio"`.
  - `test_gpu_errors_save_nothing`: GPU 429 gives 429, GPU 500 gives 500, and the store has no `versions/` object after either.
  - `test_transcribe_missing_file`: no `audio` object gives 404, and the GPU is not called.
  - `test_bad_ids_touch_no_store`: paths `/v1beta/files/..`, `/v1beta/files/not-a-uuid`, `/v1beta/files/<id>/versions/x`, `/v1beta/files/<id>/versions/..%2F` give 400, and the store has 0 calls.
  - `test_unknown_route`: `GET /v1beta/nope` gives 404.
  - `test_gcs_list_follows_pages`: `GcsStore.list` with `urllib.request.urlopen` patched to return 2 pages (the first with `nextPageToken`) returns the items of both pages.
- [ ] **Step 2:** Run `cd deployments/stt-a-qwen3-asr-diar-vertex/upload && python3 -m unittest test_upload -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. `route` checks ids with `ID_RE` / `VERSION_RE` before any store call. `meta.json` holds `{"id", "name", "mime_type", "size_bytes", "created"}` in the body and `name`, `created` as metadata. Version JSON as in the spec. The handler: `do_GET` and `do_POST` read the body (a bad `Content-Length` gives 400, inside the `try`), call `route`, and reply with CORS headers. A `201` and a GPU status pass through. GPU error bodies pass through as JSON when they parse, else as `error(text, status)`.
- [ ] **Step 4:** Run the tests again. Expected: all PASS. Then `wc -c upload.py` and compare with the Task 1 limit.
- [ ] **Step 5:** Commit: `git commit -m "feat: STT-A files service (list, history, transcribe again)"`.

### Task 3: Terraform (core bucket, files service, gateway)

**Files:**
- Modify: `infra/core/main.tf`, `infra/core/tests/core.tftest.hcl`
- Modify: `deployments/stt-a-qwen3-asr-diar-vertex/upload.tf`, `gateway.tf`, `outputs.tf` (if a name changes), `tests/upload.tftest.hcl`, `tests/gateway.tftest.hcl`

**Interfaces:**
- Consumes: the route list and env names of Task 2; the timeout facts of Task 1.

- [ ] **Step 1: Write the failing tests.**
  - `core.tftest.hcl` `stt_audio_bucket`: `length(lifecycle_rule) == 0` and `force_destroy == false` (replace the 1-day asserts).
  - `upload.tftest.hcl`: service name `stt-a-qwen3-asr-diar-files`; `local.upload_env == { AUDIO_BUCKET = "p-stt-audio", SA_EMAIL = ..., IMAGE_TAG = "0.1.0", TARGET = <the :rawPredict URL, the same expression as module.cors_proxy target> }`; a new `google_storage_bucket_iam_member.upload_read` with `roles/storage.objectViewer` on `p-stt-audio`; a new `google_project_iam_member.upload_predict` with `roles/aiplatform.user` for the files SA.
  - `gateway.tftest.hcl`: the path keys are exactly `/v1beta/files`, `/v1beta/files/{id}`, `/v1beta/files/{id}/transcribe`, `/v1beta/files/{id}/versions/{version_id}`, `/v1beta/interactions`, `/v1beta/uploads`. Every operation of every path except `/v1beta/interactions` has `x-google-backend.address == module.upload.url`. `transcribe` `post` has deadline 300; the others 30. Path parameters `id` and `version_id` are declared (`in = "path"`, `required = true`, `type = "string"`) on the operations that use them. The existing security asserts still hold.
- [ ] **Step 2:** Run `./scripts/check.py infra/core deployments/stt-a-qwen3-asr-diar-vertex`. Expected: FAIL in `test`.
- [ ] **Step 3:** Implement. Keep the Terraform name `module.upload` (fewer renames); only the service name changes (`"${local.gateway_id}-files"`). `timeout = "3600s"`. Put the `:rawPredict` URL in a local in `cors_proxy.tf` and use it in both places. If Task 1 found an endpoint timeout field, set it to 3600 s here and add a test assert.
- [ ] **Step 4:** Run `./scripts/check.py infra/core deployments/stt-a-qwen3-asr-diar-vertex`. Expected: all `ok`.
- [ ] **Step 5:** Commit: `git commit -m "feat: STT-A files service Terraform and gateway paths"`.

### Task 4: UI and mock

**Files:**
- Modify: `ui/src/App.tsx` (hash routing), `ui/src/panels/Stt.tsx`, `ui/mock-server.mjs`, `ui/src/lib.test.ts`

**Interfaces:**
- Consumes: the routes and shapes of Task 2; `call`, `curlFor`, `errorText` (`api.ts`); `Status`, `Timings`, `Curl` (`components.tsx`); the existing `groupTurns`.
- Produces: `parseHash(hash: string): { tab: string; file?: string }` exported from `ui/src/App.tsx`; `speakerCount(annotations: WordInfo[]): number` exported from `Stt.tsx`.

- [ ] **Step 1: Write the failing tests** in `ui/src/lib.test.ts`:
  - `parseHash("#/stt-mock/0b8e...")` gives `{tab: "stt-mock", file: "0b8e..."}`; `parseHash("#/tts-mock")` gives `{tab: "tts-mock"}`; `parseHash("")` gives `{tab: ""}`.
  - `speakerCount` of words with `spk_1, spk_2, spk_1` is 2; of words without `speaker` is 0.
- [ ] **Step 2:** Run `cd ui && npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement:
  - `App.tsx`: `active` uses `parseHash(location.hash).tab`.
  - `Stt.tsx`: the 2-part layout of the spec sketch. Upload of any size through `/v1beta/uploads` (now with `name`) and the signed `PUT`, then the first `transcribe` at once. Files list with Refresh. A file view with "Transcribe again" (language, speakers, label), the versions table (time, image tag, language, speakers, label, run time), 1 version in full (`groupTurns`), and 2 ticked versions side by side. The selected file goes to `#/<tab>/<file id>` and comes back from it. A 504 shows "The run can still finish. Press Refresh in a few minutes." The curl box shows the `transcribe` call.
  - `mock-server.mjs`: the 5 routes in memory (a `Map` of files with versions); `transcribe` builds the fixed 2-speaker answer and stores a version with `image_tag: "mock"`.
- [ ] **Step 4:** Run `cd ui && npm test && npm run build`. Expected: PASS.
- [ ] **Step 5:** Use the `verify-ui` skill against the mock: upload a small file (first version appears), transcribe again with label `t2`, tick 2 versions (side by side shows both), reload with the `#/stt-mock/<id>` URL (the file opens). Keep the evidence. Update `.claude/skills/verify-ui/features/stt-transcribe.md` to the new journey.
- [ ] **Step 6:** Commit: `git commit -m "feat: STT tab with stored files, versions and compare"`.

### Task 5: Docs

**Files:**
- Modify: `deployments/stt-a-qwen3-asr-diar-vertex/README.md`, `.claude/skills/model-ui/SKILL.md` (the `stt` row), `infra/README.md` (only if it names the upload service)

- [ ] **Step 1:** README: the route table with the 5 files routes; the test section uses upload, then `transcribe` (not the direct route), and says that only `transcribe` runs are saved; the real-deploy checks: a re-run makes a new version; a long file (over 300 s) gets a version or not (write down which); the bucket keeps files forever (no automatic delete) and how to delete by hand (`gcloud storage rm -r gs://$GCP_PROJECT_ID-stt-audio/files/<id>/`).
- [ ] **Step 2:** `model-ui` skill: the `stt` row describes the files routes.
- [ ] **Step 3:** Run `./scripts/check.py` and `cd ui && npm test`. Expected: all `ok`.
- [ ] **Step 4:** Commit: `git commit -m "docs: STT-A file history in the README and skills"`.
