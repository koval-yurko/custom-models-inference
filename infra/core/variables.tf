variable "project_id" {
  description = "GCP project ID. The project must exist and have billing linked."
  type        = string
}

variable "billing_account" {
  description = "Billing account ID, for example 0X0X0X-0X0X0X-0X0X0X."
  type        = string
}

variable "region" {
  description = "Region for buckets and Artifact Registry repos."
  type        = string
  default     = "us-central1"
}

variable "budget_amount" {
  description = "Monthly budget for email alerts at 50%, 90% and 100%, as a whole number in the billing account currency (USD for most accounts)."
  type        = number
  default     = 20

  validation {
    condition     = var.budget_amount > 0 && floor(var.budget_amount) == var.budget_amount
    error_message = "budget_amount must be a positive whole number."
  }
}

variable "hf_token" {
  description = "Hugging Face token. Ephemeral: it is sent to Secret Manager and never stored in state or plan."
  type        = string
  ephemeral   = true
  sensitive   = true
}

variable "slack_bot_token" {
  description = "Slack bot token (xoxb-...), scope chat:write. Ephemeral: it goes to the write-only auth_token_wo and is never stored in state or plan."
  type        = string
  ephemeral   = true
  sensitive   = true
}

variable "slack_channel" {
  description = "Slack channel for the scale notifications, for example #models. The bot must be in the channel."
  type        = string

  validation {
    condition     = startswith(var.slack_channel, "#")
    error_message = "slack_channel must start with #, for example #models."
  }
}

variable "runpod_api_key" {
  description = "Runpod API key. Ephemeral: it goes to Secret Manager (runpod-api-key) and never into state. The CORS proxy of each model reads it."
  type        = string
  ephemeral   = true
  sensitive   = true
}

variable "modal_api_key" {
  description = "Modal proxy token (wk-<id>.ws-<secret>). Ephemeral: it goes to Secret Manager (modal-api-key) and never into state. The CORS proxy of each model on Modal reads it."
  type        = string
  ephemeral   = true
  sensitive   = true
}

variable "runpod_s3_access_key" {
  description = "Runpod S3 API access key (user_...). Ephemeral: it goes to Secret Manager (runpod-s3-access-key) and never into state. scripts/runpod-weights.py --cloud reads it."
  type        = string
  ephemeral   = true
  sensitive   = true
}

variable "runpod_s3_secret_key" {
  description = "Runpod S3 API secret key (rps_...). Ephemeral: it goes to Secret Manager (runpod-s3-secret-key) and never into state."
  type        = string
  ephemeral   = true
  sensitive   = true
}

