#!/usr/bin/env bash
# Upload + deploy (or undeploy + delete) the model of a vertex-model deployment through the Vertex AI REST API.
# Run it from the deployment folder, after terraform apply. It reads `terraform output -json vertex`.
#   ../../infra/modules/vertex-model/vertex.sh deploy
#   ../../infra/modules/vertex-model/vertex.sh undeploy   # before terraform destroy
# Needs: terraform, gcloud (auth from .envrc), curl, jq.
set -euo pipefail

cmd="${1:-}"
[[ "$cmd" == deploy || "$cmd" == undeploy ]] || { echo "usage: $0 deploy|undeploy" >&2; exit 2; }

out="$(terraform output -json vertex)"
v() { jq -r "$1" <<<"$out"; }
project="$(v .project)"
region="$(v .region)"
endpoint="$(v .endpoint)"
name="$(v .name)"
api="https://${region}-aiplatform.googleapis.com/v1beta1"
token="$(gcloud auth print-access-token)"

call() { # method path [body]
  curl -sS --fail-with-body -X "$1" -H "Authorization: Bearer ${token}" -H "Content-Type: application/json" \
    "${api}/$2" ${3:+--data "$3"}
}

wait_op() { # operation name -> prints the final operation JSON; fails on an operation error
  local op="$1" res
  for _ in $(seq 1 240); do # 240 x 15 s = 60 min (deploymentTimeout max is 1800 s plus node start)
    res="$(call GET "$op")"
    if [[ "$(jq -r '.done // false' <<<"$res")" == true ]]; then
      if jq -e '.error' <<<"$res" >/dev/null; then echo "operation failed: $(jq -c .error <<<"$res")" >&2; return 1; fi
      echo "$res"
      return 0
    fi
    sleep 15
  done
  echo "timeout waiting for $op" >&2
  return 1
}

deployed_ids() { call GET "$endpoint" | jq -r '.deployedModels[]?.id'; }

if [[ "$cmd" == deploy ]]; then
  if [[ -n "$(deployed_ids)" ]]; then
    echo "The endpoint already has a deployed model. Run '$0 undeploy' first." >&2
    exit 1
  fi
  echo "Upload model ${name}..."
  op="$(call POST "projects/${project}/locations/${region}/models:upload" "$(v '.model_upload | del(.. | nulls)')" | jq -r .name)"
  model="$(wait_op "$op" | jq -r .response.model)"
  echo "Model: ${model}"

  echo "Deploy to ${endpoint} (min 0 replicas). This can take 30 minutes..."
  body="$(jq -c --arg m "$model" '{deployedModel: (.deployed_model + {model: $m} | del(.. | nulls)), trafficSplit: {"0": 100}}' <<<"$out")"
  op="$(call POST "${endpoint}:deployModel" "$body" | jq -r .name)"
  wait_op "$op" | jq -r '"Deployed model ID: " + .response.deployedModel.id'
  echo "Endpoint DNS: $(v .endpoint_dns)"
else
  for id in $(deployed_ids); do
    echo "Undeploy ${id}..."
    op="$(call POST "${endpoint}:undeployModel" "$(jq -nc --arg id "$id" '{deployedModelId: $id}')" | jq -r .name)"
    wait_op "$op" >/dev/null
  done
  # Delete every model with this display name, also one left behind by a failed deploy.
  for model in $(call GET "projects/${project}/locations/${region}/models?filter=display_name=%22${name}%22" | jq -r '.models[]?.name'); do
    echo "Delete ${model}..."
    op="$(call DELETE "$model" | jq -r .name)"
    wait_op "$op" >/dev/null
  done
  echo "Done. Run terraform destroy to remove the endpoint and the service account."
fi
