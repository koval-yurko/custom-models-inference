---
name: cloud-run-instances
description: Get the number of running Cloud Run instances for the model services in this repo (for example tts-a-kokoro-cpu). Use to check scale to zero, to see if a GPU service is still billing, or to poll instance counts on a schedule.
---

# Cloud Run instance count

Read-only. It queries the Cloud Monitoring metric `run.googleapis.com/container/instance_count`.

## Run

Run from the repo root. An agent shell does not load `.env`, so use `direnv exec`.

```sh
direnv exec . .claude/skills/cloud-run-instances/instances.sh [service]
```

- With a service name, the output is one line: `<service> <count>`.
- With no argument, the output has one line for each service that reported in the last 10 minutes.

## Read the result

- The count is the sum of `active` and `idle` instances.
- Cloud Run keeps an idle instance for about 15 minutes after the last request. A count of `1` in that time is normal.
- The metric lags by 1 to 2 minutes.
- A service with no points in the window shows `0`. This is scale to zero.
- Scale to zero is confirmed only when the count stays `0` for at least 17 minutes after the last request.
- For a GPU service (for example `llm-a-gemma4-12b-vllm`), a count above `0` means money is spent now (L4 about $1/hour).

## Report

State the count for each service and say if it is `0`. Do not change any resource. If a count stays above `0` long after the last request, tell the user. Do not delete or scale the service yourself: apply and destroy are run by the user.
