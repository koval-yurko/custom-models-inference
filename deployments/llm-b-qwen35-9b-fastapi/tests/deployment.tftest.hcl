mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id = "p"
}

run "custom_container_on_vertex" {
  command = apply

  assert {
    condition     = output.vertex.model_upload.model.containerSpec.imageUri == "us-central1-docker.pkg.dev/p/models/llm-b-qwen35-9b-fastapi:0.1.0"
    error_message = "the image must come from the models repo with the image_tag"
  }
  assert {
    condition     = output.vertex.model_upload.model.containerSpec.invokeRoutePrefix == "/*" && output.vertex.model_upload.model.containerSpec.predictRoute == null
    error_message = "every app.py route must be reachable through :invoke"
  }
  assert {
    condition     = output.vertex.model_upload.model.artifactUri == "gs://p-models/qwen3.5-9b-fp8/"
    error_message = "AIP_STORAGE_URI must point to the weights folder of the weights-copy job"
  }
  assert {
    condition     = output.vertex.deployed_model.dedicatedResources.minReplicaCount == 0
    error_message = "the endpoint must scale to 0"
  }
}
