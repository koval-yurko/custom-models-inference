# STT-A on Vertex AI: Qwen3-ASR with speaker diarization, 1 L4

Speech to text with a speaker for each word, behind the Gemini 3.5 Transcribe contract. Design: [`docs/specs/2026-11-21-stt-a-design.md`](../../docs/specs/2026-11-21-stt-a-design.md). Research: [`docs/research/06-stt-diarization.md`](../../docs/research/06-stt-diarization.md).

- 1 own GPU image (`services/speech_engine/`, `FROM vllm/vllm-openai:v0.14.0`) runs 3 models: Qwen3-ASR-1.7B (text, 30 languages), Qwen3-ForcedAligner-0.6B (word times, 11 languages) and Pyannote `speaker-diarization-community-1` (speakers). `qwen-asr` 0.0.6 pins vLLM 0.14.0, so the base is older than LLM-B.
- Pipeline: Pyannote finds the speaker turns first. Then ASR runs on each turn, and each word gets the speaker of its turn. In the 19 languages without the aligner, the word times are estimates (by character count). The speaker is always from the turn.
- Private Vertex AI endpoint in `us-central1`: `g2-standard-12`, 1 `NVIDIA_L4`. It scales to zero (max 1 replica, idle time 300 s). 1 request at a time.
- Weights: `gs://<project_id>-models/stt-a-qwen3-asr-diar/{asr,aligner,pyannote}/`. At start, `speech_engine/models.py` copies them to `/models` on the local disk.
- Public API Gateway `stt-a-qwen3-asr-diar` checks `x-api-key`:
  - `POST /v1beta/interactions` goes to the CORS proxy `stt-a-qwen3-asr-diar-proxy`, then to `:rawPredict`. Deadline 300 s.
  - `POST /v1beta/uploads` and `/v1beta/files...` go to the CPU STT API service `stt-a-qwen3-asr-diar-api` (`services/stt_api/`, own small image). It gives signed `PUT` URLs (15 minutes, up to 500 MB) for `gs://<project_id>-stt-audio/files/<id>/audio`, lists the files, and keeps the transcript history. "Transcribe again" calls `:rawPredict` and saves the answer as a new version.
- Files and versions are kept forever (no automatic delete). Only runs of `POST /v1beta/files/<id>/transcribe` are saved. A direct `/v1beta/interactions` call is not saved, so test scripts use `transcribe`.
- The test UI has a tab for it (type `stt`): the files list, the versions of a file, "Transcribe again" with a label, and 2 versions side by side.
- Evaluation: see [Evaluation](#evaluation). A reference transcript per file gives each version a WER, cpWER and DER score, and the UI shows the mean per setup.

## Code layout

```
deployments/stt-a-qwen3-asr-diar-vertex/
  *.tf, tests/                     Terraform: Vertex AI endpoint, gateway, CORS proxy, STT API service, alerts
  services/speech_engine/          speech engine (Vertex AI, GPU): the main work, audio to text with speakers
    speech_engine/main.py          HTTP server: /health, /v1beta/interactions, the setup record
    speech_engine/pipeline.py      the work: decode, diarize, transcribe each turn, time each word
    speech_engine/logic.py         pure rules: request check, turns, language map, the answer shape
    speech_engine/models.py        the 3 real models (Qwen3-ASR, ForcedAligner, Pyannote); needs the GPU
    tests/, Dockerfile, cloudbuild.yaml, requirements.txt
  services/stt_api/                STT API (Cloud Run, CPU, standard library only): what the UI calls
    stt_api/server.py              HTTP server (CORS, JSON); __main__.py starts it
    stt_api/routes.py              the route table
    stt_api/files.py               uploads and transcript history: checks, file list, speaker names
    stt_api/bucket.py              bucket layout: object names and id formats
    stt_api/gcp.py                 GCS store, signed URLs, the speech engine call (:rawPredict), tokens
    stt_api/evaluation/            extra: scores against a reference (reference.py, metrics.py, scoring.py)
    tests/, Dockerfile, cloudbuild.yaml
```

The main flow is upload, then transcribe: `stt_api` stores the file and calls `speech_engine`. The Cloud Run service is `stt-a-qwen3-asr-diar-api`. The evaluation package is an extra: it only reads stored versions and references.

| Route | Body | Answer |
|---|---|---|
| `GET /health` (private) | - | `200` when the 3 models are loaded. `503` while they load. |
| `POST /v1beta/interactions` | Gemini Interactions body: 1 audio item (`data` + `mime_type`, or `file_uri` `gs://<project_id>-stt-audio/...`), `transcription_config` with `language_codes` and `mode` | `output_text` and `steps[0].content[0].annotations[]` of type `word_info` (`text`, `speaker`, `start_offset`, `end_offset`) |
| `POST /v1beta/uploads` | `{"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 123}` | `id`, `upload_url`, `method`, `headers`, `file_uri`, `expires_in` |
| `GET /v1beta/files` | - | `{"files": [{"id", "name", "mime_type", "size_bytes", "created", "versions", "latest", "reference"}]}`, newest first |
| `GET /v1beta/files/<id>` | - | `{"file", "versions": [...]}`: version summaries, newest first |
| `GET /v1beta/files/<id>/versions/<version_id>` | - | 1 full version: `label`, `image_tag`, `settings`, `setup` (the models and the image tag that made the version), `run_seconds`, `response`, plus `names` (`{}` when none) |
| `PUT /v1beta/files/<id>/versions/<version_id>/names` | `{"spk_1": "Alice"}`: at most 8 keys `spk_<n>`, names 1 to 40 chars | `{"names": {...}}`. Replaces all names of that version. `{}` removes them |
| `GET /v1beta/files/<id>/audio` | - | `{"url", "mime_type", "expires_in": 900}`: a signed `GET` URL of the audio, for playback |
| `PUT /v1beta/files/<id>/reference` | `{"language": "en", "turns": [{"speaker": "Alice", "start"?: "00:00:00.0", "end"?: "00:00:04.9", "text": "..."}]}` | The stored reference. A new PUT replaces it |
| `GET /v1beta/files/<id>/reference` | - | The reference, or `404` when the file has none |
| `GET /v1beta/files/<id>/versions/<version_id>/score` | - | `wer`, `cpwer`, `mapping` (`{"spk_1": "Alice"}`), `der` (`{der, missed, false_alarm, confusion}` or `null`), `ref_speakers`, `hyp_speakers`, `speed`, `setup`. `404` without a reference |
| `GET /v1beta/scores` | - | `{"rows": [1 score per version of each file with a reference], "setups": [{setup, files, versions, wer, cpwer, der}]}` |
| `POST /v1beta/files/<id>/transcribe` | `{"language_codes"?: ["en"], "diarization"?: true, "label"?: "..."}` | `201` with the new version. A GPU `429` (cold start) or error comes back as is, and nothing is saved |

Limits: 30 minutes of audio, 20 MB inline, 8 speakers, 600 s of GPU time per request (Vertex AI endpoint timeout). Errors are HTTP 400 with `{"error": {"code", "message", "status"}}`.

## Deploy

Do `infra/core` first (see `infra/README.md`). It makes the gateway API `stt-a-qwen3-asr-diar` and the bucket `<project_id>-stt-audio`. Run the commands from the repo root.

0. Accept the user conditions of [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) with the Hugging Face account of `HF_TOKEN`. Without it, the Pyannote copy in step 1 fails.
1. Sync the HCP workspace (new: `custom-models-stt-a-qwen3-asr-diar-vertex`). Apply core again for the bucket and the gateway API. Then check the L4 quota. The weights check fails until step 2 is done.
   ```sh
   ./scripts/hcp-sync.py
   cd infra/core && terraform init && terraform apply && cd ../..
   ./scripts/preflight.py --weights stt-a-qwen3-asr-diar --l4
   ```
2. Copy the weights: 3 runs into 1 folder. Skip a run when its folder already has files.
   ```sh
   gcloud storage ls gs://$GCP_PROJECT_ID-models/stt-a-qwen3-asr-diar/
   gcloud run jobs execute weights-copy --wait --update-env-vars HF_REPO=Qwen/Qwen3-ASR-1.7B,TARGET_DIR=stt-a-qwen3-asr-diar/asr
   gcloud run jobs execute weights-copy --wait --update-env-vars HF_REPO=Qwen/Qwen3-ForcedAligner-0.6B,TARGET_DIR=stt-a-qwen3-asr-diar/aligner
   gcloud run jobs execute weights-copy --wait --update-env-vars HF_REPO=pyannote/speaker-diarization-community-1,TARGET_DIR=stt-a-qwen3-asr-diar/pyannote
   ```
3. Build the 2 images with Cloud Build. They go to the `models` repo. Each tag must be the same as in `variables.tf`: `image_tag` for the GPU service, `stt_api_image_tag` for the STT API service. The files image takes about 1 minute.
   ```sh
   gcloud builds submit deployments/stt-a-qwen3-asr-diar-vertex/services/speech_engine \
     --config=deployments/stt-a-qwen3-asr-diar-vertex/services/speech_engine/cloudbuild.yaml \
     --substitutions=_REGION=$GCP_REGION,_TAG=0.1.4 --region=$GCP_REGION
   gcloud builds submit deployments/stt-a-qwen3-asr-diar-vertex/services/stt_api \
     --config=deployments/stt-a-qwen3-asr-diar-vertex/services/stt_api/cloudbuild.yaml \
     --substitutions=_REGION=$GCP_REGION,_TAG=0.2.0 --region=$GCP_REGION
   ```
4. Apply. It makes the endpoint, the gateway, the CORS proxy, the STT API service and the Slack alerts.
   ```sh
   cd deployments/stt-a-qwen3-asr-diar-vertex && terraform init && terraform apply && cd ../..
   ```
5. Upload and deploy the model. It takes up to 45 minutes.
   ```sh
   ./scripts/vertex.py deploy deployments/stt-a-qwen3-asr-diar-vertex
   ```
6. Update the test UI (new tab, new panel code).
   ```sh
   ./scripts/ui-deploy.py
   ```

### Update an existing deployment

Use these steps after a code change. Run the commands from the repo root. Raise the tag in `variables.tf` for each image that changed (`image_tag` for `services/speech_engine`, `stt_api_image_tag` for `services/stt_api`), and use the same tags in step 1. A change only in `services/stt_api` needs steps 1, 3 and 5 only (no GPU step: Cloud Run starts the new revision).

1. Build the 2 images. Do this before step 3: without the `stt-a-qwen3-asr-diar-api` image, the new service does not start.
   ```sh
   gcloud builds submit deployments/stt-a-qwen3-asr-diar-vertex/services/speech_engine \
     --config=deployments/stt-a-qwen3-asr-diar-vertex/services/speech_engine/cloudbuild.yaml \
     --substitutions=_REGION=$GCP_REGION,_TAG=0.1.4 --region=$GCP_REGION
   gcloud builds submit deployments/stt-a-qwen3-asr-diar-vertex/services/stt_api \
     --config=deployments/stt-a-qwen3-asr-diar-vertex/services/stt_api/cloudbuild.yaml \
     --substitutions=_REGION=$GCP_REGION,_TAG=0.2.0 --region=$GCP_REGION
   gcloud artifacts docker images list $GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/models --include-tags \
     --filter="package~stt-a-qwen3-asr-diar" --format="table(package,tags)"
   ```
   Expected: `stt-a-qwen3-asr-diar` with tag `0.1.4` and `stt-a-qwen3-asr-diar-api` with tag `0.2.0`.
2. Undeploy the GPU model. The model upload holds the image tag, so a new image needs a new upload.
   ```sh
   ./scripts/vertex.py undeploy deployments/stt-a-qwen3-asr-diar-vertex
   ```
3. Check, then apply.
   ```sh
   ./scripts/check.py deployments/stt-a-qwen3-asr-diar-vertex
   cd deployments/stt-a-qwen3-asr-diar-vertex && terraform init && terraform apply && cd ../..
   ```
4. Upload and deploy the model with the new image. It takes up to 45 minutes.
   ```sh
   ./scripts/vertex.py deploy deployments/stt-a-qwen3-asr-diar-vertex
   ```
5. Deploy the test UI (new panel code), then compare the gateway URL in the deployed `models.json` with the Terraform output.
   ```sh
   ./scripts/ui-deploy.py
   curl -s https://storage.googleapis.com/$GCP_PROJECT_ID-ui/models.json | grep -o 'https://stt-a-qwen3-asr-diar[^"]*'
   cd deployments/stt-a-qwen3-asr-diar-vertex && terraform output -raw gateway_url && cd ../..
   ```
6. Test the new routes through the gateway: see [Test](#test) and [Evaluation](#evaluation).

## Evaluation

Compare model setups on your own files. A setup is what made a version: the GPU service adds `setup` (`asr`, `aligner`, `diarization`, `image_tag`) to each answer, from the `SETUP_*` env in `main.tf`, and the STT API service saves it with the version. A version without a `setup` shows as `unknown`.

1. Pick a stored file. In the UI, open "Reference" under the versions table.
2. Write the correct transcript, 1 turn per line: `[00:00:00.0 - 00:00:04.9] Alice: Hello.` The times are optional. Without them, there is no DER. JSON in the route format is also accepted.
3. To start from a model answer, tick a version and press "Draft from version". Correct the words and the speaker names, then press "Save reference". So each reviewed transcript becomes test data.
4. Each version of that file now shows cpWER, WER, DER, speed and the speaker mapping. "use as names" saves the mapping as the speaker names of that version.
5. To test a change (a new model, a new setting): change the `SETUP_*` values in `main.tf` with it, raise `image_tag`, deploy, then "Transcribe again" on the files with a reference. "Accuracy per setup" shows the mean scores of each setup side by side.

The metrics (all computed on read in `services/stt_api/stt_api/evaluation/`, standard library only). The text of both sides is normalized first: lowercase, no punctuation, single spaces.

- WER: word errors (substitutions + deletions + insertions) / reference words. Text only.
- cpWER (CHiME-6): the words of each speaker are joined, and each model speaker maps to the 1 reference speaker that gives the fewest errors (Hungarian method). Text and speakers. This is the main score.
- DER: 10 ms frames, a 0.25 s collar around each reference turn boundary. Missed speech + false alarm + speaker confusion, as a share of the reference speaker time. Only when every reference turn has times.
- Speed: audio seconds / run seconds of the version.

Limit: the words are split on spaces, so WER and cpWER do not fit Chinese, Japanese or Thai (no spaces between words).

## Test

At 0 replicas the first call returns HTTP 429. The loop sends the call again every 30 s, for at most 30 minutes. It prints the time to the first `200`: this is the cold start. Use a short recording of 2 people (`/tmp/two.wav`, 20 MB or less).

```sh
cd deployments/stt-a-qwen3-asr-diar-vertex
GW=$(terraform output -raw gateway_url)
KEY=$(terraform -chdir=../../infra/core output -raw api_key)
python3 -c "import base64,json; print(json.dumps({'input':[{'type':'audio','mime_type':'audio/wav','data':base64.b64encode(open('/tmp/two.wav','rb').read()).decode()}],'generation_config':{'transcription_config':{'mode':{'type':'verbatim','diarization_mode':'speaker','timestamp_granularities':['word']}}}}))" > /tmp/stt-body.json
start=$(date +%s)
for i in $(seq 1 60); do
  code=$(curl -s -o /tmp/out.json -w '%{http_code}' -X POST "$GW/v1beta/interactions" \
    -H "x-api-key: $KEY" -H "Content-Type: application/json" -d @/tmp/stt-body.json)
  [ "$code" != 429 ] && break
  sleep 30
done
echo "$code after $(( $(date +%s) - start )) s"; python3 -m json.tool /tmp/out.json | head -40
```

Expected: `200`, the text in `output_text`, and `word_info` items with `spk_1` and `spk_2`.

Stored file and transcript history (any size, up to 500 MB). Use this for tests after a change: every run is saved as a version.

```sh
F=/tmp/long.mp3; SIZE=$(wc -c < $F | tr -d ' ')
curl -s -X POST "$GW/v1beta/uploads" -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d "{\"name\":\"$(basename $F)\",\"mime_type\":\"audio/mpeg\",\"size_bytes\":$SIZE}" > /tmp/up.json
ID=$(python3 -c "import json; print(json.load(open('/tmp/up.json'))['id'])")
URL=$(python3 -c "import json; print(json.load(open('/tmp/up.json'))['upload_url'])")
curl -s -X PUT "$URL" -H "Content-Type: audio/mpeg" -H "x-goog-content-length-range: 0,$SIZE" --data-binary @$F -w '%{http_code}\n'
curl -s -X POST "$GW/v1beta/files/$ID/transcribe" -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d '{"diarization": true, "label": "first run"}' -w '\n%{http_code}\n' | tail -c 300
curl -s "$GW/v1beta/files/$ID" -H "x-api-key: $KEY" | python3 -m json.tool | head -40
```

Expected: `200` for the `PUT`, `201` for `transcribe`, and 1 version in the file. At 0 replicas, `transcribe` returns `429` first: send it again every 30 s, as in the loop above. To test a change later, send only the `transcribe` call with the same `ID` and a new label, then compare the versions in the UI.

Evaluation. Use the same `GW`, `KEY` and `ID`. Write the correct transcript of the file in the reference, not the text below.

```sh
curl -s -X PUT "$GW/v1beta/files/$ID/reference" -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d '{"language": "en", "turns": [{"speaker": "Alice", "start": "00:00:00.0", "end": "00:00:04.9", "text": "Hello, this is the first speaker."}, {"speaker": "Bob", "start": "00:00:05.0", "end": "00:00:09.0", "text": "Hi, I am the second speaker."}]}' -w '\n%{http_code}\n'
V=$(curl -s "$GW/v1beta/files/$ID" -H "x-api-key: $KEY" | python3 -c "import json,sys; print(json.load(sys.stdin)['versions'][0]['id'])")
curl -s "$GW/v1beta/files/$ID/versions/$V" -H "x-api-key: $KEY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('setup'))"
curl -s "$GW/v1beta/files/$ID/versions/$V/score" -H "x-api-key: $KEY" | python3 -m json.tool
curl -s "$GW/v1beta/scores" -H "x-api-key: $KEY" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['setups'], indent=1))"
```

Expected: `200` for the `PUT`. The newest version has a `setup` with `image_tag` `0.1.4`. The score has `wer`, `cpwer`, `der`, `mapping` (`spk_1` to `Alice`) and `speed`. `scores` has 1 row per setup.

Delete a stored file by hand (there is no delete route): `gcloud storage rm -r gs://$GCP_PROJECT_ID-stt-audio/files/<id>/`.

Verified on 2026-11-21 (image 0.1.2): through the gateway, `transcribe` on a stored 2-speaker file returned HTTP 201 with the exact text, 37 `word_info` items, and the turns `spk_1`, `spk_2`, `spk_1` in the right places. The version was saved, and the live test UI showed it, made a second version with a label, and showed both side by side. `models ready` is in the Vertex AI logs. The 3 models fit on the L4 with `GPU_MEMORY_UTILIZATION=0.5` and `MAX_MODEL_LEN=16384`. The aligner words have no punctuation (`output_text` keeps it).

Verified on 2026-11-22 (image 0.1.3): `transcribe` on the same stored `two.wav` through the gateway returned HTTP 201 after a scale-up from 0. The version `20261122T134028Z-4b20` (label `0.1.3 check`, `image_tag` 0.1.3) has the same `output_text` as the 0.1.2 version, 37 `word_info` items and the turns `spk_1` 0.03-4.91 s, `spk_2` 5.04-8.96 s, `spk_1` 9.06-12.58 s. GPU run 8.4 s (first request after the start).

Checks only a real deploy can do (write the results here):

1. The 3 models fit on the 24 GB L4 (vLLM `gpu_memory_utilization=0.5`). If the load fails with CUDA out of memory, lower it in `speech_engine/models.py`.
2. The log line `models ready` is in the Vertex AI logs after the cold start.
3. If you have Gemini 3.5 Transcribe access: compare the field names of a real answer (`steps[].type`, `content[].type`) with this service.
4. "Transcribe again" on a stored file makes a new version: `GET /v1beta/files/<id>` shows 1 more version.
5. A long file (more than 300 s of processing): the gateway returns `504`. Press Refresh in the UI after a few minutes, and write down if the version still appears (Cloud Run keeps the request running) or not. A run over 600 s of GPU time fails on the Vertex AI side.

## Cold start and speed

| Date | Image tag | Event | Time | Notes |
|---|---|---|---|---|
| 2026-11-21 | 0.1.2 | First deploy (`vertex.py deploy`: model upload, node start, image pull, weights copy, model load) | 24 min (17:23 to 17:47 UTC) | Node and image pull about 18 min (first container log 17:41). Weights copy (6.5 GB to `/tmp/models`) and the load of the 3 models about 4 min: `models ready` at 17:45:01. vLLM: KV cache 3.5 GiB, `torch.compile` 41 s. |
| 2026-11-21 | 0.1.3 | Deploy, attempt 1 (`vertex.py deploy`) | Failed after 28.5 min (22:41:31 to 23:10:05 UTC) | Node and image pull 24 min (first container log 23:05:27). The container was healthy: weights copy 67 s, `models ready` at 23:08:57, `/health` 200. Then the operation failed with code 13 "System error. Please try this operation again" and Vertex AI stopped the container. Slack got "scaled to 0" from that stop. No cause in the logs. |
| 2026-11-21 | 0.1.3 | Deploy, attempt 2 (same command, the uploaded model is reused) | 12 min (23:10:38 to 23:22:43 UTC) | First container log after 6.4 min (the node probably had the image). Weights copy 63 s, `models ready` 3 min 42 s after the container start. |
| 2026-11-22 | 0.1.3 | Scale up from 0 (first `transcribe` call to HTTP 201) | 7 min 19 s (13:33:18 to 13:40:37 UTC) | Container start after 3 min 14 s, weights copy 69 s, `models ready` at 13:40:12 (6 min 54 s). A try on 2026-11-21 reached `models ready` in 7 min 3 s, but the next call got no answer (the connection closed after 75 s, no log in the STT API service). A new gateway config went live a few minutes before. |

Weights copy (from the container start to the first vLLM log line): 89 s with 0.1.2 (1 file at a time), 63 to 67 s with 0.1.3 (`transfer_manager`, 16 threads). The gain is about 25 s. The node start and the image pull take most of the cold start, and the weights copy does not change them. The 0.1.3 log shows `Connection pool is full ... Connection pool size: 10`: 16 threads share 10 connections.

Real-time factor (processing time / audio length) through the gateway, warm:

| Date | Audio | Language | Speakers | Time | RTF |
|---|---|---|---|---|---|
| 2026-11-21 | `two.wav`, 12.6 s, macOS `say` voices | English (auto) | 2 | 8.4 s (first request after the deploy) | 0.67 |
| 2026-11-21 | same file | English (`en`) | 2 | 1.0 s (warm) | 0.08 |

## Check scale to zero

Send no requests for about 15 minutes (idle time 300 s plus the check interval). Then the replica count must be `0`: open the endpoint in the console (Vertex AI > Online prediction > Endpoints) and look at the replica chart. The next call must return `429` first.

Slack: after a cold start, the channel gets `🟢 STT-A Qwen3 ASR + speakers is ready`. After the scale down, it gets `⚪ STT-A Qwen3 ASR + speakers scaled to 0`. See [Scale notifications (Slack)](../../infra/README.md#scale-notifications-slack). The STT API service is CPU only and has no alerts.

## Destroy

Undeploy first. Vertex AI does not delete an endpoint that has a deployed model.

```sh
./scripts/vertex.py undeploy deployments/stt-a-qwen3-asr-diar-vertex
cd deployments/stt-a-qwen3-asr-diar-vertex && terraform destroy
```

The weights, the image and the audio bucket (in core) stay. Delete the 2 images with `gcloud artifacts docker images delete $GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/models/stt-a-qwen3-asr-diar --delete-tags` and the same command for `stt-a-qwen3-asr-diar-api`. Delete the empty HCP workspace `custom-models-stt-a-qwen3-asr-diar-vertex` in the HCP UI.

## Local checks (no GCP)

```sh
./scripts/check.py deployments/stt-a-qwen3-asr-diar-vertex        # Terraform + Python unit tests
cd deployments/stt-a-qwen3-asr-diar-vertex/services/speech_engine && uv run --with fastapi --with httpx --with numpy python -m unittest discover -s tests -t .
cd deployments/stt-a-qwen3-asr-diar-vertex/services/stt_api && python3 -m unittest discover -s tests -t .
```
