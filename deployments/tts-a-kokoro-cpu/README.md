# TTS-A: Kokoro-82M on CPU

Kokoro-82M text to speech with the stock image `ghcr.io/remsky/kokoro-fastapi-cpu:v0.10.0`. It has an OpenAI-compatible API (`POST /v1/audio/speech`).

- Cloud Run service `tts-a-kokoro-cpu` in `europe-west4`, 4 vCPU, 8 GiB, no GPU.
- The image comes through the remote repo `ghcr` from `infra/core/`. The model weights are inside the image.
- Scales to zero (min 0, max 1). The Cloud Run URL is private: only `INVOKER_EMAIL` and the gateway service account can call it.
- Public access goes through API Gateway (`gateway.tf`, region `europe-west1`). The gateway checks the `x-api-key` header before it calls Cloud Run, so a request without a valid key does not start an instance.
- Only `POST /v1/audio/speech` and `GET /v1/audio/voices` go through the gateway.
- The gateway has streaming, so chunked audio comes through as it is made. Terraform cannot turn streaming on. `scripts/gateway-streaming.py` does it after the apply.

## Prerequisites

1. Set up `.env` and direnv as in `infra/README.md` (section "HCP Terraform (state and runs)"). Run the commands below from a shell where direnv has loaded `.env`.
2. Apply `infra/core/` first. It enables the API Gateway APIs, and creates the gateway API `tts-a-kokoro-cpu` and the shared API key. See `infra/README.md`, section "API Gateway and API keys".
3. Put `GCP_PROJECT_ID` and `INVOKER_EMAIL` (your Google account) in `.env`. `.envrc` maps them to Terraform variables.

## Apply

```sh
cd deployments/tts-a-kokoro-cpu
terraform init
terraform apply   # runs on HCP Terraform; the terminal streams the output
```

## Turn on gateway streaming (after every apply that creates the gateway)

Terraform creates the gateway without streaming. Streaming can only be set when a gateway is created. The script deletes the gateway and creates it again with streaming and the same ID. Then it imports the gateway into the state if the state does not have it, and runs `terraform apply -refresh-only`.

WARNING: The gateway URL changes, and the gateway is not available for some minutes.

Run it from the repo root. It loads `.env` itself, so you do not need direnv. See `infra/README.md`, section "Streaming".

```sh
./scripts/gateway-streaming.py deployments/tts-a-kokoro-cpu   # add --yes to skip the prompt
```

The script does nothing when the gateway already has streaming. Run it again after Terraform replaces the gateway (for example, after you change `gateway_region`).

## Test call through the gateway

```sh
GW=$(terraform output -raw gateway_url)
KEY=$(terraform -chdir=../../infra/core output -raw api_key)   # shared key for all gateways

# No key: the gateway returns 401 and no instance starts.
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$GW/v1/audio/speech"

# Complete file
curl -sS -X POST "$GW/v1/audio/speech" -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d '{"model":"kokoro","input":"Hello from the gateway.","voice":"af_heart","response_format":"mp3","stream":false}' \
  -o gw.mp3 && file gw.mp3

# Streaming: the server makes audio in chunks of 175 to 250 tokens. A short text is 1 chunk, so it
# cannot show streaming. Use a long text (40 sentences, about 3 minutes of audio).
TEXT=$(for i in $(seq 1 40); do printf 'This is sentence number %s, and it is long enough to carry a few words of plain speech. ' "$i"; done)
curl -sS -N -X POST "$GW/v1/audio/speech" -H "x-api-key: $KEY" -H "Content-Type: application/json" \
  -d "{\"model\":\"kokoro\",\"input\":\"$TEXT\",\"voice\":\"af_heart\",\"response_format\":\"pcm\",\"stream\":true}" \
  -o gw.pcm -w 'first byte: %{time_starttransfer}s, total: %{time_total}s\n'
# Streaming works when the first byte comes after a few seconds and the total after about 2 minutes.
# Without streaming, the first byte and the total are almost the same.
```

All gateways use one shared API key from `infra/core/`. The gateway allows a request to take 300 s at most, including the cold start.

## Test call (direct to Cloud Run)

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
