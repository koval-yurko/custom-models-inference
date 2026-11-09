terraform {
  # Set the bucket at init: terraform init -backend-config="bucket=<project_id>-tfstate"
  backend "gcs" {
    prefix = "deployments/tts-a-kokoro-cpu"
  }
}
