# One-time setup, applied locally (its own local state, separate from the app):
#   - S3 bucket that stores Terraform state for the CI environments
#   - GitHub OIDC provider + IAM role that GitHub Actions assumes (no stored AWS keys)

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "eu-north-1"
}

variable "project_name" {
  type    = string
  default = "handseller"
}

variable "github_repository" {
  description = "GitHub repository in the form owner/repo"
  type        = string
  default     = "sanabatool15/handseller-bookkeeping"
}

variable "github_environments" {
  description = "GitHub Environments allowed to assume the deploy role"
  type        = list(string)
  default     = ["develop", "test", "prod"]
}

variable "create_oidc_provider" {
  description = "Set to false if this AWS account already has the GitHub OIDC provider"
  type        = bool
  default     = true
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
  }
}

# ---------- Terraform state bucket ----------
resource "aws_s3_bucket" "state" {
  bucket = "${var.project_name}-terraform-state-${local.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------- GitHub OIDC ----------
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  tags           = local.tags
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions" {
  name = "github-actions-${var.project_name}-deploy"
  tags = local.tags

  # Only jobs that run in one of the listed GitHub Environments can assume this role
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = [
            for e in var.github_environments : "repo:${var.github_repository}:environment:${e}"
          ]
        }
      }
    }]
  })
}

# Services Terraform creates for the app
locals {
  managed_policies = {
    lambda     = "arn:aws:iam::aws:policy/AWSLambda_FullAccess"
    apigateway = "arn:aws:iam::aws:policy/AmazonAPIGatewayAdministrator"
    cloudfront = "arn:aws:iam::aws:policy/CloudFrontFullAccess"
    iam_read   = "arn:aws:iam::aws:policy/IAMReadOnlyAccess"
  }
}

resource "aws_iam_role_policy_attachment" "github" {
  for_each   = local.managed_policies
  role       = aws_iam_role.github_actions.name
  policy_arn = each.value
}

# S3 limited to this project's buckets (app buckets + state bucket); IAM limited to this project's roles
resource "aws_iam_role_policy" "github_scoped" {
  name = "github-actions-${var.project_name}-scoped"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "s3:*"
        Resource = [
          "arn:aws:s3:::${var.project_name}-*",
          "arn:aws:s3:::${var.project_name}-*/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateAssumeRolePolicy",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy", "iam:ListRolePolicies",
          "iam:ListInstanceProfilesForRole", "iam:TagRole", "iam:UntagRole", "iam:PassRole"
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/${var.project_name}-*"
      }
    ]
  })
}

output "state_bucket_name" {
  value = aws_s3_bucket.state.id
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions.arn
}
