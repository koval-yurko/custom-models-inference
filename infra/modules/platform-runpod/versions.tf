terraform {
  required_version = ">= 1.11"

  required_providers {
    runpod = {
      source  = "runpod/runpod"
      version = "~> 2.0"
    }
  }
}
