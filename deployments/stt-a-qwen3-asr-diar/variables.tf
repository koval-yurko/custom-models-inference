variable "project_id" {
  description = "GCP project ID (the infra/core project)."
  type        = string
}

variable "region" {
  description = "Region. Must match the infra/core region."
  type        = string
  default     = "us-central1"
}

variable "image_tag" {
  description = "Tag of the GPU image that services/speech_engine/cloudbuild.yaml pushed to the models repo. Change it for each new build."
  type        = string
  default     = "0.2.5"
}

variable "stt_api_image_tag" {
  description = "Tag of the STT API service image that services/stt_api/cloudbuild.yaml pushed to the models repo. Change it for each new build."
  type        = string
  default     = "0.4.0"
}

variable "gateway_region" {
  description = "API Gateway region. API Gateway is not in every region; it can differ from var.region."
  type        = string
  default     = "europe-west1"
}

variable "modal_workspace" {
  description = "Modal workspace name (.env MODAL_PROFILE). The Modal web URL is https://<workspace>--stt-a-qwen3-asr-diar.modal.run."
  type        = string
}
