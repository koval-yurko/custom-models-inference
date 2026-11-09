# TTS-A: Kokoro-82M on CPU

Kokoro-82M text to speech with the stock image `ghcr.io/remsky/kokoro-fastapi-cpu:v0.10.0`. It has an OpenAI-compatible API (`POST /v1/audio/speech`).

- Cloud Run service `tts-a-kokoro-cpu` in `europe-west4`, 4 vCPU, 8 GiB, no GPU.
- The image comes through the bootstrap remote repo `ghcr`. The model weights are inside the image.
- Scales to zero (min 0, max 1). Private: only `INVOKER_EMAIL` can call it.

## Prerequisites

1. Set up `.env` and direnv as in `infra/bootstrap/README.md` (section "State (HCP Terraform)"). Run the commands below from a shell where direnv has loaded `.env`.
2. Apply `infra/bootstrap` first.
3. Put `GCP_PROJECT_ID` and `INVOKER_EMAIL` (your Google account) in `.env`. `.envrc` maps them to Terraform variables.

## Apply

```sh
cd deployments/tts-a-kokoro-cpu
terraform init
terraform apply
```

## Test call

The token comes from the service account in `.env`. The service account must be in `invokers` (the module grants `run.invoker` only to the listed members). If the call returns 403, add `serviceAccount:<email>` to `invokers`.

The first call after an idle period starts an instance. It can take 20 to 60 s.

```sh
URL=$(terraform output -raw url)
curl -sS -X POST "$URL/v1/audio/speech" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences="$URL")" \
  -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello from Cloud Run.","voice":"af_heart","response_format":"mp3"}' \
  -o out.mp3 && file out.mp3
```

Expected: `out.mp3: ... MPEG ADTS, layer III` (or `Audio file with ID3`). If the file is small text, read it: it is the error message.

## Check scale to zero

Send no requests for about 15 minutes. Then check the instance count:

```sh
PROJECT=$GCP_PROJECT_ID
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
gcloud run services list
```

`tts-a-kokoro-cpu` must not be in the list.
