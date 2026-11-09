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
  default     = "europe-west4"
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
