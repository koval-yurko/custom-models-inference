#!/usr/bin/env bash
# Print "<service> <instance count>" for Cloud Run services. Usage: instances.sh [service]
# Loads the repo .env itself (like scripts/*.py), so it needs no direnv: run it directly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
if [ -z "${GCP_PROJECT_ID:-}" ] && [ -f "$ROOT/.env" ]; then
  set -a; . "$ROOT/.env"; set +a
fi
# Same gcloud identity as .envrc: the service account key and the repo-local config dir.
if [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
  export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE="${CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE:-$GOOGLE_APPLICATION_CREDENTIALS}"
  export CLOUDSDK_CONFIG="${CLOUDSDK_CONFIG:-$ROOT/.gcloud}"
fi

svc="${1:-}"
filter='metric.type="run.googleapis.com/container/instance_count"'
[ -n "$svc" ] && filter+=" AND resource.labels.service_name=\"$svc\""

# macOS date first, then GNU date.
start=$(date -u -v-10M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '-10 min' +%Y-%m-%dT%H:%M:%SZ)
end=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# REDUCE_SUM adds the active and idle series; the newest point is first.
curl -sS -G "https://monitoring.googleapis.com/v3/projects/$GCP_PROJECT_ID/timeSeries" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  --data-urlencode "filter=$filter" \
  --data-urlencode "interval.startTime=$start" \
  --data-urlencode "interval.endTime=$end" \
  --data-urlencode "aggregation.alignmentPeriod=60s" \
  --data-urlencode "aggregation.perSeriesAligner=ALIGN_MAX" \
  --data-urlencode "aggregation.crossSeriesReducer=REDUCE_SUM" \
  --data-urlencode "aggregation.groupByFields=resource.labels.service_name" |
  python3 -c '
import json, sys
d = json.load(sys.stdin)
if "error" in d:
    sys.exit(d["error"]["message"])
rows = {s["resource"]["labels"]["service_name"]: s["points"][0]["value"]["int64Value"] for s in d.get("timeSeries", [])}
want = sys.argv[1]
if want:
    rows.setdefault(want, "0")  # no points in the window = scaled to zero
for name, n in sorted(rows.items()):
    print(name, n)
' "$svc"
