# Shared — resources that outlive and span every environment.
#
# Today that is exactly one thing: the ECR registry.
#
# ## Why this directory exists
#
# The registry module was originally instantiated inside `envs/dev` (and the
# staging tfvars example declared the SAME repository names). That made a shared
# resource owned by an environment's state, which fails three ways:
#
#   1. Standing staging up in the same account fails with
#      RepositoryAlreadyExistsException — or, forced through, leaves two states
#      managing one resource and racing each other's lifecycle policies.
#   2. `envs/dev` is documented as destroy-and-rebuild and runs with
#      ecr_force_delete = true. That destroy deletes the shared repositories and
#      every image in them, including staging's.
#   3. The repositories were encrypted with the DEV environment's CMK, so
#      destroying dev also scheduled deletion of the key protecting staging's
#      image layers.
#
# The registry module's own documentation says repositories are shared across
# environments and distinguished by image TAG, not by repository name. That design
# is kept — it is what makes "the exact bytes tested in dev are promoted to
# staging" true. What changes is ownership: a shared resource gets a shared state.
#
# This directory carries the same account guard the environments do
# (terraform_data.account_guard below) — applying to the wrong account is a hard
# error, not a warning.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}

locals {
  tags = {
    Project = "mortgageboss-ai"
    # Deliberately NOT an Environment tag: this is shared, and tagging it with any
    # one environment would make the per-environment budget filters double-count it.
    Scope     = "shared"
    ManagedBy = "terraform"
  }
}

data "aws_caller_identity" "current" {}

# Same account guard as the environments: a precondition, not a check, so applying
# to the wrong account is a hard error rather than a warning.
resource "terraform_data" "account_guard" {
  input = var.aws_account_id

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Wrong AWS account: credentials resolve to ${data.aws_caller_identity.current.account_id} but var.aws_account_id is ${var.aws_account_id}. Refusing to apply."
    }
  }
}

# --------------------------------------------------------------------------- #
# KMS — image encryption
#
# The registry needs a key whose lifetime matches the registry's. It must NOT be
# an environment's CMK: destroying that environment would schedule deletion of the
# key protecting every other environment's image layers.
#
# No explicit key policy is needed here, unlike the environments' key: nothing
# writes CloudWatch Logs with this key, so the default root policy is sufficient
# and ECR creates its grants through the caller's own permissions.
# --------------------------------------------------------------------------- #

# Skipped entirely when registry_kms_key_arn is supplied — the migration path,
# where repositories already exist under an environment's CMK and ECR cannot
# re-encrypt them in place.
resource "aws_kms_key" "registry" {
  count = var.registry_kms_key_arn == null ? 1 : 0

  description             = "mbai shared — ECR image encryption at rest."
  enable_key_rotation     = true
  deletion_window_in_days = var.kms_deletion_window_days

  tags = merge(local.tags, { Name = "mbai-shared-registry" })
}

# See ADR-365 and var.kms_create_alias: a destroy orphans an alias, so this is a
# knob rather than an assumption.
resource "aws_kms_alias" "registry" {
  count = var.registry_kms_key_arn == null && var.kms_create_alias ? 1 : 0

  name          = "alias/mbai-shared-registry"
  target_key_id = aws_kms_key.registry[0].key_id
}

locals {
  registry_kms_key_arn = coalesce(var.registry_kms_key_arn, one(aws_kms_key.registry[*].arn))
}

# --------------------------------------------------------------------------- #
# Cost allocation
#
# Account-level, which is why it is here and not in an environment. Every
# environment's budget filters on user:Environment$<name>, and AWS Budgets matches
# NOTHING until the tag is activated — a filtered budget without this reports $0
# forever and never fires.
# --------------------------------------------------------------------------- #

resource "aws_ce_cost_allocation_tag" "environment" {
  count = var.activate_environment_cost_allocation_tag ? 1 : 0

  tag_key = "Environment"
  status  = "Active"
}

# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

module "registry" {
  source = "../modules/registry"

  tags = local.tags

  repository_names     = var.ecr_repository_names
  kms_key_arn          = local.registry_kms_key_arn
  keep_last_images     = var.ecr_keep_last_images
  untagged_expire_days = var.ecr_untagged_expire_days

  protected_tag_prefixes     = var.ecr_protected_tag_prefixes
  keep_last_protected_images = var.ecr_keep_last_protected_images

  # ⚠️ false, and it should stay false. This registry now holds EVERY
  # environment's images, so a destroy here is not a dev rebuild — it is the loss
  # of all image history. Emptying a repository is a deliberate console action.
  force_delete = var.ecr_force_delete
}
