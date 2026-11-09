# State is in HCP Terraform. The organization comes from TF_CLOUD_ORGANIZATION in the root .env (loaded by direnv, see .envrc).
# Workspace: execution mode must be "Local" (the run uses your gcloud credentials).
terraform {
  cloud {
    workspaces {
      name = "custom-models-llm-a-gemma4-12b-vllm"
    }
  }
}
