# TTS-A: Kokoro-82M on CPU

Kokoro-82M text to speech with the stock image `ghcr.io/remsky/kokoro-fastapi-cpu:v0.10.0`. It has an OpenAI-compatible API (`POST /v1/audio/speech`).

- Cloud Run service `tts-a-kokoro-cpu` in `europe-west4`, 4 vCPU, 8 GiB, no GPU.
- The image comes through the bootstrap remote repo `ghcr`. The model weights are inside the image.
- Scales to zero (min 0, max 1). Private: only `invoker_email` can call it.

## Prerequisites

1. Apply `infra/bootstrap` first.
2. Put `project_id` and `invoker_email` (your Google account) in `terraform.tfvars`.

## Apply

```sh
cd deployments/tts-a-kokoro-cpu
terraform init -backend-config="bucket=<project_id>-tfstate"
terraform apply
```

## Test call

The first call after an idle period starts an instance. It can take 20 to 60 s.

```sh
URL=$(terraform output -raw url)
curl -sS -X POST "$URL/v1/audio/speech" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello from Cloud Run.","voice":"af_heart","response_format":"mp3"}' \
  -o out.mp3 && file out.mp3
```

Expected: `out.mp3: ... MPEG ADTS, layer III` (or `Audio file with ID3`). If the file is small text, read it: it is the error message.

## Check scale to zero

Send no requests for about 15 minutes. Then check the instance count:

```sh
PROJECT=<project_id>
START=$(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ)   # Linux: date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ
END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl -sS -G "https://monitoring.googleapis.com/v3/projects/$PROJECT/timeSeries" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  --data-urlencode 'filter=metric.type="run.googleapis.com/container/instance_count" AND resource.labels.service_name="tts-a-kokoro-cpu"' \
  --data-urlencode "interval.startTime=$START" \
  --data-urlencode "interval.endTime=$END"
```

The newest points must show `0` (or the series has no recent points). You can also open the service in the console, go to the Metrics tab and look at "Container instance count".

## Destroy

```sh
terraform destroy
gcloud run services list --region europe-west4
```

`tts-a-kokoro-cpu` must not be in the list.
