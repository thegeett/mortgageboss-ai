# Development environment — wires the four modules together.
#
# Staging is a sibling directory with different variable values, not different
# code. Nothing environment-specific may move from here into a module.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
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
    Project     = "mortgageboss-ai"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # Secrets Manager uses a slash-delimited path; every other resource uses the
  # dash-delimited name_prefix.
  secret_path_prefix = "mbai/${var.environment}" # pragma: allowlist secret

  log_group_names = [
    "/ecs/${var.name_prefix}/api",
    "/ecs/${var.name_prefix}/worker",
    "/ecs/${var.name_prefix}/frontend",
  ]
}

data "aws_caller_identity" "current" {}

# Account guard. A `precondition` rather than a `check` block: a check only emits
# a WARNING, and applying this to the wrong account must be a hard error. Quotas
# were once requested against the wrong account in this project — the same mistake
# with Terraform has materially worse consequences.
resource "terraform_data" "account_guard" {
  input = var.aws_account_id

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Wrong AWS account: credentials resolve to ${data.aws_caller_identity.current.account_id} but var.aws_account_id is ${var.aws_account_id}. Refusing to apply."
    }
  }
}

# The documents bucket is hand-created (C0) and deliberately OUTSIDE Terraform's
# management — it holds uploaded files and must survive every destroy. Looked up,
# never created, never imported.
data "aws_s3_bucket" "documents" {
  bucket = var.documents_bucket_name
}

# --------------------------------------------------------------------------- #
# Modules
# --------------------------------------------------------------------------- #

module "network" {
  source = "../../modules/network"

  name_prefix = var.name_prefix
  tags        = local.tags
  aws_region  = var.aws_region

  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones

  enable_nat_gateway          = var.enable_nat_gateway
  enable_vpc_endpoints        = var.enable_vpc_endpoints
  interface_endpoint_services = var.interface_endpoint_services
}

module "secrets" {
  source = "../../modules/secrets"

  name_prefix        = var.name_prefix
  tags               = local.tags
  secret_path_prefix = local.secret_path_prefix

  recovery_window_days     = var.secret_recovery_window_days
  kms_deletion_window_days = var.kms_deletion_window_days
  kms_create_alias         = var.kms_create_alias

  # Same variable drives the data module's auth setting, so the secret's existence
  # and the cache's auth requirement cannot drift apart.
  create_redis_url_secret = var.redis_auth_enabled
}

# The registry is NOT here. It lives in ../../shared, because it is shared across
# environments (distinguished by image tag, not repository name) and a shared
# resource cannot be owned by one environment's state.
#
# Owning it here meant this environment's documented destroy-and-rebuild — which
# runs with ecr_force_delete = true — would delete every environment's images, and
# would schedule deletion of the CMK protecting them. See ../../shared/main.tf.
#
# Read the repository URLs with:
#   terraform -chdir=../../shared output ecr_repository_urls

module "data" {
  source = "../../modules/data"

  name_prefix = var.name_prefix
  tags        = local.tags

  private_subnet_ids      = module.network.private_subnet_ids
  rds_security_group_id   = module.network.rds_security_group_id
  redis_security_group_id = module.network.redis_security_group_id
  kms_key_arn             = module.secrets.kms_key_arn

  postgres_version                 = var.postgres_version
  postgres_family                  = var.postgres_family
  rds_instance_class               = var.rds_instance_class
  rds_allocated_storage            = var.rds_allocated_storage
  rds_max_allocated_storage        = var.rds_max_allocated_storage
  rds_multi_az                     = var.rds_multi_az
  rds_deletion_protection          = var.rds_deletion_protection
  rds_skip_final_snapshot          = var.rds_skip_final_snapshot
  rds_backup_retention_days        = var.rds_backup_retention_days
  rds_performance_insights_enabled = var.rds_performance_insights_enabled
  database_name                    = var.database_name
  database_username                = var.database_username

  redis_node_type    = var.redis_node_type
  redis_version      = var.redis_version
  redis_family       = var.redis_family
  redis_auth_enabled = var.redis_auth_enabled

  log_group_names    = local.log_group_names
  log_retention_days = var.log_retention_days
}

# --------------------------------------------------------------------------- #
# Budget alarm
#
# This environment is meant to be destroyed between uses. The budget is what
# catches the case where it was not.
# --------------------------------------------------------------------------- #

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Scoped to THIS environment's tag. Without the filter the budget aggregated the
  # whole account, so standing staging up in the same account made a $150 "dev"
  # budget fire at $120 of COMBINED spend — and both environments' budgets would
  # alarm on the same number, destroying the alert's only job: saying which
  # environment was left running.
  #
  # Depends on default_tags applying Environment to every resource in this root
  # module (see the provider block). Untagged/unTaggable spend — the shared registry,
  # data-transfer lines AWS does not attribute — falls outside every environment
  # budget by construction; that is the correct trade for an attributable alert.
  # format(), not a template string. AWS wants the literal form
  # "user:<TagKey>$<TagValue>", and in HCL `$${` is the ESCAPE for a literal `${` —
  # so "user:Environment$${var.environment}" evaluates to the literal text
  # "user:Environment${var.environment}", a tag value nothing ever matches. That
  # budget would have tracked $0 and never fired, which is worse than no filter at
  # all because it looks configured. Verified: format() yields "user:Environment$dev".
  #
  # ⚠️ DEPENDS ON AN ACCOUNT-LEVEL ACTIVATION. AWS Budgets can only filter on a
  # user-defined tag once `Environment` is ACTIVATED as a cost allocation tag, which
  # is an account (payer) setting, not a per-environment one — it is applied by
  # `aws_ce_cost_allocation_tag.environment` in ../../shared. Without that this
  # filter matches zero cost records and the budget silently never fires. Activation
  # is also NOT retroactive, so the first period after enabling is partial.
  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:Environment$%s", var.environment)]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_notification_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_notification_email]
  }
}
