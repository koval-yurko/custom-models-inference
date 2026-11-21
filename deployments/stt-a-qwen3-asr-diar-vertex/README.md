# STT-A on Vertex AI: Qwen3-ASR with speaker diarization, 1 L4

Speech to text with a speaker for each word, behind the Gemini 3.5 Transcribe contract. Design: [`docs/specs/2026-11-21-stt-a-design.md`](../../docs/specs/2026-11-21-stt-a-design.md). Research: [`docs/research/06-stt-diarization.md`](../../docs/research/06-stt-diarization.md).

- 1 own image (`image/`, `FROM vllm/vllm-openai:v0.14.0`) runs 3 models: Qwen3-ASR-1.7B (text, 30 languages), Qwen3-ForcedAligner-0.6B (word times, 11 languages) and Pyannote `speaker-diarization-community-1` (speakers). `qwen-asr` 0.0.6 pins vLLM 0.14.0, so the base is older than LLM-B.
- Pipeline: Pyannote finds the speaker turns first. Then ASR runs on each turn, and each word gets the speaker of its turn. In the 19 languages without the aligner, the word times are estimates (by character count). The speaker is always from the turn.
- Private Vertex AI endpoint in `us-central1`: `g2-standard-12`, 1 `NVIDIA_L4`. It scales to zero (max 1 replica, idle time 300 s). 1 request at a time.
- Weights: `gs://<project_id>-models/stt-a-qwen3-asr-diar/{asr,aligner,pyannote}/`. At start, `app/models.py` copies them to `/models` on the local disk.
- Public API Gateway `stt-a-qwen3-asr-diar` checks `x-api-key`:
  - `POST /v1beta/interactions` goes to the CORS proxy `stt-a-qwen3-asr-diar-proxy`, then to `:rawPredict`. Deadline 300 s.
  - `POST /v1beta/uploads` and `/v1beta/files...` go to the CPU files service `stt-a-qwen3-asr-diar-files` (`upload/upload.py`). It gives signed `PUT` URLs (15 minutes, up to 500 MB) for `gs://<project_id>-stt-audio/files/<id>/audio`, lists the files, and keeps the transcript history. "Transcribe again" calls `:rawPredict` and saves the answer as a new version.
- Files and versions are kept forever (no automatic delete). Only runs of `POST /v1beta/files/<id>/transcribe` are saved. A direct `/v1beta/interactions` call is not saved, so test scripts use `transcribe`.
- The test UI has a tab for it (type `stt`): the files list, the versions of a file, "Transcribe again" with a label, and 2 versions side by side.

| Route | Body | Answer |
|---|---|---|
| `GET /health` (private) | - | `200` when the 3 models are loaded. `503` while they load. |
| `POST /v1beta/interactions` | Gemini Interactions body: 1 audio item (`data` + `mime_type`, or `file_uri` `gs://<project_id>-stt-audio/...`), `transcription_config` with `language_codes` and `mode` | `output_text` and `steps[0].content[0].annotations[]` of type `word_info` (`text`, `speaker`, `start_offset`, `end_offset`) |
| `POST /v1beta/uploads` | `{"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 123}` | `id`, `upload_url`, `method`, `headers`, `file_uri`, `expires_in` |
| `GET /v1beta/files` | - | `{"files": [{"id", "name", "mime_type", "size_bytes", "created", "versions", "latest"}]}`, newest first |
| `GET /v1beta/files/<id>` | - | `{"file", "versions": [...]}`: version summaries, newest first |
| `GET /v1beta/files/<id>/versions/<version_id>` | - | 1 full version: `label`, `image_tag`, `settings`, `run_seconds`, `response` |
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
3. Build the image with Cloud Build. It pushes to the `models` repo. The tag must be the same as `image_tag` in `variables.tf`.
   ```sh
   gcloud builds submit deployments/stt-a-qwen3-asr-diar-vertex/image \
     --config=deployments/stt-a-qwen3-asr-diar-vertex/image/cloudbuild.yaml \
     --substitutions=_REGION=$GCP_REGION,_TAG=0.1.2 --region=$GCP_REGION
   ```
4. Apply. It makes the endpoint, the gateway, the CORS proxy, the files service and the Slack alerts.
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

To change the code: raise `image_tag` in `variables.tf`, build with the new `_TAG`, run `./scripts/vertex.py undeploy deployments/stt-a-qwen3-asr-diar-vertex`, then `terraform apply`, then `vertex.py deploy`.

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

Delete a stored file by hand (there is no delete route): `gcloud storage rm -r gs://$GCP_PROJECT_ID-stt-audio/files/<id>/`.

Verified on 2026-11-21 (image 0.1.2): through the gateway, `transcribe` on a stored 2-speaker file returned HTTP 201 with the exact text, 37 `word_info` items, and the turns `spk_1`, `spk_2`, `spk_1` in the right places. The version was saved, and the live test UI showed it, made a second version with a label, and showed both side by side. `models ready` is in the Vertex AI logs. The 3 models fit on the L4 with `GPU_MEMORY_UTILIZATION=0.5` and `MAX_MODEL_LEN=16384`. The aligner words have no punctuation (`output_text` keeps it).

Checks only a real deploy can do (write the results here):

1. The 3 models fit on the 24 GB L4 (vLLM `gpu_memory_utilization=0.5`). If the load fails with CUDA out of memory, lower it in `app/models.py`.
2. The log line `models ready` is in the Vertex AI logs after the cold start.
3. If you have Gemini 3.5 Transcribe access: compare the field names of a real answer (`steps[].type`, `content[].type`) with this service.
4. "Transcribe again" on a stored file makes a new version: `GET /v1beta/files/<id>` shows 1 more version.
5. A long file (more than 300 s of processing): the gateway returns `504`. Press Refresh in the UI after a few minutes, and write down if the version still appears (Cloud Run keeps the request running) or not. A run over 600 s of GPU time fails on the Vertex AI side.

## Cold start and speed

| Date | Image tag | Event | Time | Notes |
|---|---|---|---|---|
| 2026-11-21 | 0.1.2 | First deploy (`vertex.py deploy`: model upload, node start, image pull, weights copy, model load) | 24 min (17:23 to 17:47 UTC) | Node and image pull about 18 min (first container log 17:41). Weights copy (6.5 GB to `/tmp/models`) and the load of the 3 models about 4 min: `models ready` at 17:45:01. vLLM: KV cache 3.5 GiB, `torch.compile` 41 s. |
| - | 0.1.2 | Scale up from 0 | - | Measure on the next call at 0 replicas. |

Real-time factor (processing time / audio length) through the gateway, warm:

| Date | Audio | Language | Speakers | Time | RTF |
|---|---|---|---|---|---|
| 2026-11-21 | `two.wav`, 12.6 s, macOS `say` voices | English (auto) | 2 | 8.4 s (first request after the deploy) | 0.67 |
| 2026-11-21 | same file | English (`en`) | 2 | 1.0 s (warm) | 0.08 |

## Check scale to zero

Send no requests for about 15 minutes (idle time 300 s plus the check interval). Then the replica count must be `0`: open the endpoint in the console (Vertex AI > Online prediction > Endpoints) and look at the replica chart. The next call must return `429` first.

Slack: after a cold start, the channel gets `🟢 STT-A Qwen3 ASR + speakers is ready`. After the scale down, it gets `⚪ STT-A Qwen3 ASR + speakers scaled to 0`. See [Scale notifications (Slack)](../../infra/README.md#scale-notifications-slack). The files service is CPU only and has no alerts.

## Destroy

Undeploy first. Vertex AI does not delete an endpoint that has a deployed model.

```sh
./scripts/vertex.py undeploy deployments/stt-a-qwen3-asr-diar-vertex
cd deployments/stt-a-qwen3-asr-diar-vertex && terraform destroy
```

The weights, the image and the audio bucket (in core) stay. Delete the image with `gcloud artifacts docker images delete $GCP_REGION-docker.pkg.dev/$GCP_PROJECT_ID/models/stt-a-qwen3-asr-diar --delete-tags`. Delete the empty HCP workspace `custom-models-stt-a-qwen3-asr-diar-vertex` in the HCP UI.

## Local checks (no GCP)

```sh
./scripts/check.py deployments/stt-a-qwen3-asr-diar-vertex        # Terraform + Python unit tests
cd deployments/stt-a-qwen3-asr-diar-vertex/image && uv run --with fastapi --with httpx --with numpy python -m unittest tests.test_main
```
