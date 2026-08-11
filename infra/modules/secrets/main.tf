# Secrets — a customer-managed KMS key and the Secrets Manager CONTAINERS.
#
# ┌─────────────────────────────────────────────────────────────────────────┐
# │ THIS MODULE CREATES EMPTY SECRETS. IT NEVER CREATES A SECRET VALUE.      │
# │                                                                         │
# │ There is deliberately no random_password, no aws_secretsmanager_secret_ │
# │ version, and no variable carrying key material anywhere in this module.  │
# │ A value written by Terraform is a value stored in state, printed in a    │
# │ plan diff, and replaceable by a provider upgrade. The operator populates │
# │ each secret once with the AWS CLI — see README.md.                       │
# │                                                                         │
# │ ENCRYPTION_KEY in particular MUST NOT be Terraform-generated. Rotating   │
# │ it permanently destroys every stored borrower SSN. See README.md.        │
# └─────────────────────────────────────────────────────────────────────────┘

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  # Secret containers this module manages. `database-url` is included even though
  # the database module generates the password, because the URL is ASSEMBLED and
  # written by the operator — see the data module's README for why the generated
  # password is not written to the secret by Terraform.
  base_secrets = [
    "database-url",
    "jwt-secret-key",
    "encryption-key",
  ]

  secret_names = concat(
    local.base_secrets,
    var.create_redis_url_secret ? ["redis-url"] : [],
  )
}

resource "aws_kms_key" "this" {
  description             = "${var.name_prefix} - application data encryption (RDS, ECR, Secrets Manager, CloudWatch Logs)."
  enable_key_rotation     = true
  deletion_window_in_days = var.kms_deletion_window_days

  tags = merge(var.tags, { Name = var.name_prefix })
}

# Optional, and off for throwaway environments — see var.kms_create_alias.
#
# `terraform destroy` schedules the KEY for deletion but leaves the ALIAS behind
# (hashicorp/terraform-provider-aws#35161). The orphaned alias is what makes the
# next apply fail with AlreadyExistsException, not the key's deletion window: a
# fresh apply creates a new key without complaint. Skipping the alias removes the
# only manual step from destroy-and-rebuild, and costs nothing functional —
# everything references the key by ARN via this module's outputs.
resource "aws_kms_alias" "this" {
  count = var.kms_create_alias ? 1 : 0

  name          = "alias/${var.name_prefix}"
  target_key_id = aws_kms_key.this.key_id
}

# CloudWatch Logs cannot use a KMS key unless the key policy lets the logs
# service encrypt with it. Without this the log-group resources fail at apply
# with an opaque InvalidParameterException.
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_kms_key_policy" "this" {
  key_id = aws_kms_key.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableIAMUserPermissions"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${data.aws_region.current.name}.amazonaws.com" }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:Describe*",
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:*"
          }
        }
      },
    ]
  })
}

resource "aws_secretsmanager_secret" "this" {
  for_each = toset(local.secret_names)

  name        = "${var.secret_path_prefix}/${each.value}"
  description = "${var.name_prefix} - ${each.value}. Value populated out of band; never by Terraform."
  kms_key_id  = aws_kms_key.this.arn

  recovery_window_in_days = var.recovery_window_days

  tags = merge(var.tags, { Name = "${var.secret_path_prefix}/${each.value}" })

  # No `lifecycle { ignore_changes = [secret_string] }` here, deliberately.
  #
  # secret_string is an attribute of aws_secretsmanager_secret_VERSION, which this
  # module does not create — so there is no version resource for Terraform to
  # overwrite and nothing to ignore. Adding an ignore_changes block to THIS
  # resource would only suppress drift on the container's own attributes (name,
  # description, KMS key), which is the opposite of what is wanted: those SHOULD
  # be managed.
  #
  # The value is protected by the absence of a resource, not by an ignore rule.
  # If a version resource is ever added here, it needs ignore_changes then — and
  # it should not be added. See README.md.
}
