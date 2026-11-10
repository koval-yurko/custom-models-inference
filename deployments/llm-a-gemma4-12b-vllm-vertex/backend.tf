# State is in HCP Terraform. The organization comes from TF_CLOUD_ORGANIZATION in the root .env (loaded by direnv, see .envrc).
# Runs are remote on HCP Terraform. Variables and GOOGLE_CREDENTIALS come from the workspace; run ./scripts/hcp-sync.py after you change .env.
terraform {
  cloud {
    workspaces {
      name = "custom-models-llm-a-gemma4-12b-vllm-vertex"
    }
  }
}
