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
  description = "Tag of the image that image/cloudbuild.yaml pushed to the models repo. Change it for each new build."
  type        = string
  default     = "0.2.2"
}

variable "gateway_region" {
  description = "API Gateway region. API Gateway is not in every region; it can differ from var.region."
  type        = string
  default     = "europe-west1"
}
