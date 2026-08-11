# Bootstrap — the Terraform state backend itself.
#
# Chicken-and-egg: the S3 backend needs a bucket that Terraform has not created
# yet. This directory therefore uses LOCAL state, is applied ONCE, and is then
# left alone. Everything else (infra/envs/*) uses the S3 backend this creates.
#
# ONE ACCOUNT, ONE STATE. This bootstraps the staging account only. There is no
# tooling account to bootstrap: envs/dev is never applied, and production will be a
# separate account with its own bootstrap. That is why this stays a single
# directory with a single local state rather than needing workspaces.
#
# See README.md in this directory before touching anything here.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately NO backend block — this is the local-state directory.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "mortgageboss-ai"
      ManagedBy = "terraform"
    }
  }
}

variable "aws_region" {
  description = "Region for the state bucket and lock table."
  type        = string
}

variable "aws_account_id" {
  description = "Expected AWS account id. The guard below refuses to apply anywhere else."
  type        = string
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket holding Terraform state."
  type        = string
}

data "aws_caller_identity" "current" {}

# Account guard. A precondition (not a `check` block) because a `check` only
# emits a WARNING — applying this to the wrong account must be a hard error.
# Quotas were once requested against the wrong account in this project; the same
# mistake with Terraform is materially worse.
resource "terraform_data" "account_guard" {
  input = var.aws_account_id

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Wrong AWS account: credentials resolve to ${data.aws_caller_identity.current.account_id} but var.aws_account_id is ${var.aws_account_id}. Refusing to apply."
    }
  }
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name

  # State is the one thing whose loss is unrecoverable — protect it from a
  # careless `terraform destroy` in this directory.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-KMS using the AWS-managed `aws/s3` key rather than a customer-managed key.
# A CMK here would be a second chicken-and-egg (the CMK that protects state would
# itself need state) and costs $1/month for no added control: the threat model for
# the state bucket is "someone without S3 access reads it", which the managed key
# already covers. The application's own CMK is created in modules/secrets.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ⚠️ THERE IS NO DYNAMODB LOCK TABLE, deliberately.
#
# State locking uses S3 conditional writes (`use_lockfile = true` in every
# backend), which the S3 backend has supported since Terraform 1.10 and which
# deprecated `dynamodb_table` in 1.11. One fewer resource, one fewer thing to
# create before anything else can run, and no second service in the critical path
# of every plan.
#
# Nothing was ever applied, so no table exists to migrate away from — see the
# result doc.

output "state_bucket" {
  description = "S3 bucket holding Terraform state — referenced by envs/staging/backend.tf."
  value       = aws_s3_bucket.state.id
}
