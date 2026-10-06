variable "project_name" {
  description = "Name prefix for all resources"
  type        = string
  default     = "handseller"
  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name))
    error_message = "Project name must contain only lowercase letters, numbers, and hyphens."
  }
}

variable "environment" {
  description = "Environment name (dev = original manual stack, develop/test/prod = CI environments)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "develop", "test", "prod"], var.environment)
    error_message = "Environment must be one of: dev, develop, test, prod."
  }
}

variable "aws_region" {
  description = "AWS region for Lambda, API Gateway and S3"
  type        = string
  default     = "eu-north-1"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 30
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 1024
}

variable "api_throttle_burst_limit" {
  description = "API Gateway throttle burst limit"
  type        = number
  default     = 50
}

variable "api_throttle_rate_limit" {
  description = "API Gateway throttle rate limit"
  type        = number
  default     = 25
}

# All backend settings (Supabase, Redis, Inngest, JWT, LLM...) live here.
# Set it in terraform/secrets.auto.tfvars, which is git-ignored.
variable "lambda_env" {
  description = "Environment variables for the Lambda function"
  type        = map(string)
  sensitive   = true
}
