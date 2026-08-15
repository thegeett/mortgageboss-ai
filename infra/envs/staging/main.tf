# Staging environment — the first and only environment that is applied.
#
# `../dev` is a reference template that is never applied. Every difference between
# the two is a VALUE, not code: nothing environment-specific may move into a module.

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

# ⚠️ DIFFERENT FROM THE LOWER ENVIRONMENT, deliberately.
#
# There, the documents bucket was hand-made and left unmanaged. Here it is created
# by Terraform and CMK-encrypted, because it holds real borrower files: the CMK
# gives a separate audit trail and a revocation lever that the AWS-managed key does
# not. prevent_destroy guards it — the bucket holds the only copy of every uploaded
# document, and the database stores keys rather than content.
module "documents" {
  source = "../../modules/documents"

  bucket_name = var.documents_bucket_name
  tags        = local.tags
  kms_key_arn = local.documents_kms_key_arn
}

locals {
  # documents_bucket_kms_key_arn was a DEAD input — declared, set to null, and never
  # read, so changing it looked like it configured the bucket CMK and did nothing.
  # Null still means "this environment's own CMK"; an override now actually applies.
  #
  # The same value feeds S3_KMS_KEY_ID below, because the application must send the
  # key the bucket's default encryption expects — otherwise every upload is rejected.
  documents_kms_key_arn = coalesce(var.documents_bucket_kms_key_arn, module.secrets.kms_key_arn)
}

# --------------------------------------------------------------------------- #
# DNS and TLS
#
# The dns module knows nothing about the load balancer, and the alias record below
# lives here rather than inside it. That split is what keeps the graph acyclic:
# compute needs the certificate ARN for its HTTPS listener, while the alias record
# needs the ALB — so dns -> compute -> alias record, with no cycle.
# --------------------------------------------------------------------------- #

module "dns" {
  source = "../../modules/dns"

  name_prefix = var.name_prefix
  tags        = local.tags
  domain_name = var.domain_name
  enable_tls  = var.enable_tls
}

# Zone apex -> ALB. An ALIAS, not a CNAME: a zone apex cannot carry a CNAME, and an
# alias is resolved by Route 53 itself at no query cost.
resource "aws_route53_record" "apex" {
  zone_id = module.dns.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = module.compute.alb_dns_name
    zone_id                = module.compute.alb_zone_id
    evaluate_target_health = false
  }
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

  # Interface endpoints are ENIs billed per endpoint PER AZ, so confining them to
  # one AZ roughly halves their cost. Safe here only because there is no redundancy
  # to lose: desired_count is 1 and the database is single-AZ.
  endpoint_availability_zones = var.endpoint_availability_zones

  # Empty means unrestricted. A lever, not a default — see the variable.
  alb_ingress_cidr_blocks = var.allowed_cidr_blocks
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
# Unlike the dev template, this environment is NOT destroyed between uses — it has
# 30-day recovery windows, deletion protection, and prevent_destroy on the documents
# bucket. The budget here is an ordinary cost guard: it catches an unintended scale-up
# or a runaway workload, not a forgotten teardown.
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
  # module (see the provider block). Untagged/unTaggable spend — data-transfer lines
  # AWS does not attribute — falls outside every environment
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
  # `aws_ce_cost_allocation_tag.environment` in THIS root module. Without it this
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

# --------------------------------------------------------------------------- #
# Compute (C3) — ECS cluster, three Fargate services, ALB, per-task IAM
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Registry
#
# ECR lives HERE, in the same account as everything that pulls from it.
#
# It was previously its own state (`infra/shared`) with a dedicated KMS key,
# repository policies, and cross-account grant plumbing — a whole mechanism whose
# only consumer was this environment. It also carried a nasty failure mode: a
# cross-account pull missing the kms:Decrypt grant fails with an authorization
# error naming KMS, not ECR, which sends you looking in the wrong service.
#
# ⚠️ C4 recorded that repository URLs had to be ASSEMBLED from a variable because
# `data.aws_ecr_repository` resolves through THIS environment's provider and failed
# with RepositoryNotFoundException against the other account. THAT CONSTRAINT IS
# GONE — the registry is in this account and in this state, so a module output is
# now the correct source and no lookup is needed at all. Do not re-apply the old
# reasoning.
#
# Encryption uses the ENVIRONMENT CMK rather than a dedicated key: one fewer key to
# create, protect from deletion, and reason about.
# --------------------------------------------------------------------------- #

module "registry" {
  source = "../../modules/registry"

  tags = local.tags

  repository_names     = values(var.ecr_repository_names)
  kms_key_arn          = module.secrets.kms_key_arn
  keep_last_images     = var.ecr_keep_last_images
  untagged_expire_days = var.ecr_untagged_expire_days

  protected_tag_prefixes     = var.ecr_protected_tag_prefixes
  keep_last_protected_images = var.ecr_keep_last_protected_images

  # pull_account_ids is deliberately NOT set, so it takes its empty default and no
  # repository policy is created at all. The resource remains in the module,
  # count-gated, because production may genuinely need a cross-account pull later —
  # at which point it would serve two accounts rather than one.

  force_delete = var.ecr_force_delete
}

locals {
  ecr_repository_urls = {
    for key, name in var.ecr_repository_names :
    key => module.registry.repository_urls[name]
  }

  ecr_repository_arns_by_key = {
    for key, name in var.ecr_repository_names :
    key => module.registry.repository_arns[name]
  }
}

# --------------------------------------------------------------------------- #
# Cost allocation
#
# ⚠️ MOVED HERE FROM THE DISSOLVED SHARED STATE, and it is load-bearing.
#
# The budget below filters on user:Environment$<name>, and AWS Budgets matches
# NOTHING until that tag is ACTIVATED as a cost allocation tag. Without this the
# budget reports $0 forever and never fires — silently, because it looks configured.
#
# The resource is ACCOUNT-level, not environment-level. It lives in this root
# module because this account has exactly one environment; a second environment in
# the SAME account must not declare it again, or the two states would fight over
# one account-wide setting.
#
# ⚠️ AND IT CANNOT BE APPLIED FROM THIS ACCOUNT AT ALL. C5's phase-1 apply failed
# here with:
#   AccessDeniedException: Failed to update Cost Allocation Tag: Linked account
#   doesn't have access to cost allocation tags.
# Cost Explorer tag activation is MANAGEMENT-ACCOUNT ONLY. 058190633983 is a member
# account in the organization, so no permission grant inside it can make this
# succeed — it is an organizational boundary, not a policy gap.
#
# ⚠️ THE RESOURCE STAYS, count-gated to 0 by
# `activate_environment_cost_allocation_tag = false` in terraform.tfvars. Deleting
# it would delete the only statement in this configuration that the budget below
# depends on something nobody has done yet. The failure it guards against is
# SILENT: an inactive tag makes the budget's cost_filter match nothing, so it
# reports $0 forever and never fires, while looking correctly configured in the
# console. A commented-out resource is a note; a count-gated one is a note the
# `terraform plan` output keeps mentioning.
#
# What must happen instead: activate `Environment` from the MANAGEMENT account
# (Billing -> Cost allocation tags), once, by hand. Up to 24 hours before it
# reports, and the budget alarm is inert until then. See infra/README.md and the
# C5 pre-handover checklist.
#
# If this ever moves into a management-account root module, set the variable true
# THERE, not here.
# --------------------------------------------------------------------------- #

resource "aws_ce_cost_allocation_tag" "environment" {
  count = var.activate_environment_cost_allocation_tag ? 1 : 0

  tag_key = "Environment"
  status  = "Active"
}

locals {
  # Bedrock ARNs, assembled here so the module stays account- and region-free.
  #
  # BOTH lists are required to invoke a cross-region inference profile: the call
  # authorises against the profile ARN and against the underlying foundation-model
  # ARN in whichever region Bedrock routes to.
  bedrock_inference_profile_arns = [
    for id in values(var.bedrock_model_ids) :
    "arn:aws:bedrock:${var.aws_region}:${var.aws_account_id}:inference-profile/${id}"
  ]

  # The foundation-model id is the profile id minus its `us.` routing prefix.
  bedrock_foundation_model_arns = distinct(flatten([
    for id in values(var.bedrock_model_ids) : [
      for r in var.bedrock_profile_regions :
      "arn:aws:bedrock:${r}::foundation-model/${replace(id, "/^us\\./", "")}"
    ]
  ]))
}

module "compute" {
  source = "../../modules/compute"

  name_prefix = var.name_prefix
  tags        = local.tags
  aws_region  = var.aws_region

  vpc_id                = module.network.vpc_id
  public_subnet_ids     = module.network.public_subnet_ids
  alb_security_group_id = module.network.alb_security_group_id

  # ⚠️ TASKS GO IN THE SAME AZs AS THE ENDPOINTS. A task in an AZ with no local
  # endpoint still works — private DNS resolves VPC-wide — but every AWS call
  # crosses an AZ boundary, adding transfer cost and giving back the AZ
  # independence the single-AZ placement was meant to buy.
  private_subnet_ids = [
    for az in var.endpoint_availability_zones :
    module.network.private_subnet_ids_by_az[az]
  ]

  ecs_tasks_security_group_id = module.network.ecs_tasks_security_group_id

  # C7 -- lets the migrate task definition (which the `query` stage runs on) obtain an
  # IAM auth token for the read-only database role. Scoped to that one db user.
  db_instance_resource_id = module.data.db_instance_resource_id

  api_image        = "${local.ecr_repository_urls["api"]}:${var.image_tag}"
  frontend_image   = "${local.ecr_repository_urls["frontend"]}:${var.image_tag}"
  cpu_architecture = var.cpu_architecture

  api_cpu         = var.api_cpu
  api_memory      = var.api_memory
  worker_cpu      = var.worker_cpu
  worker_memory   = var.worker_memory
  frontend_cpu    = var.frontend_cpu
  frontend_memory = var.frontend_memory
  desired_count   = var.desired_count

  # Every one of these has an application default that silently behaves like local
  # development — see docs/secrets-audit.md Note 5. STORAGE_BACKEND is the sharpest:
  # left at "local" the app starts happily and writes documents to ephemeral
  # container disk that vanishes on task replacement, with NO error.
  environment_variables = merge({
    ENVIRONMENT     = var.environment
    LOG_FORMAT      = "json"
    STORAGE_BACKEND = "s3"
    S3_BUCKET       = var.documents_bucket_name
    S3_REGION       = var.aws_region

    # ⚠️ REQUIRED for a CMK-encrypted bucket. app/storage/s3.py sends
    # ServerSideEncryption=aws:kms + SSEKMSKeyId ONLY when this is set; unset, it
    # sends AES256 (SSE-S3) instead, which conflicts with the bucket's KMS default.
    S3_KMS_KEY_ID        = local.documents_kms_key_arn
    CORS_ALLOWED_ORIGINS = jsonencode(var.cors_allowed_origins)
    AI_PROVIDER          = "bedrock"
    BEDROCK_REGION       = var.aws_region

    BEDROCK_MODEL_CLASSIFICATION = var.bedrock_model_ids["classification"]
    BEDROCK_MODEL_EXTRACTION     = var.bedrock_model_ids["extraction"]
    BEDROCK_MODEL_REASONING      = var.bedrock_model_ids["reasoning"]

    AI_REQUESTS_PER_MINUTE_BEDROCK = tostring(var.ai_requests_per_minute_bedrock)

    # ⚠️ REDIS_URL IS NOT HERE. redis_auth_enabled is true in this environment, so
    # the URL carries an AUTH token and is a CREDENTIAL — it is injected from the
    # redis-url secret in secret_arns below.
    #
    # It was a plain env var holding host/port only, which worked exactly until the
    # operator applied the AUTH token that check "redis_auth_token_applied" demands.
    # From that moment every Redis and Celery call failed NOAUTH Authentication
    # required, with a correctly populated secret sitting unused.
    #
    # It must appear in ONE of the two maps, never both: ECS rejects a container
    # definition that names the same key in `environment` and `secrets`.
    },
    # With auth OFF the URL is topology only, so it stays config. ⚠️ Both parts of
    # this value matter — transit encryption makes rediss:// mandatory, and without
    # ?ssl_cert_reqs=required redis-py verifies the certificate while kombu resolves
    # to CERT_NONE.
    var.redis_auth_enabled ? {} : {
      REDIS_URL = "rediss://${module.data.redis_primary_endpoint}:6379/0?ssl_cert_reqs=required"
    },
  )

  frontend_environment_variables = {
    NODE_ENV = "production"
    # NEXT_PUBLIC_API_URL is absent on purpose — it is inlined into the JavaScript
    # bundle at BUILD time and is not read at runtime (C1). Setting it here would
    # do nothing while appearing to work.
  }

  # DATABASE_URL carries the master password; JWT and encryption keys are secrets
  # by definition. Injected by the ECS agent via the EXECUTION role, so no task
  # role needs secretsmanager:GetSecretValue.
  secret_arns = merge(
    {
      DATABASE_URL   = module.secrets.secret_arns["database-url"]
      JWT_SECRET_KEY = module.secrets.secret_arns["jwt-secret-key"]
      ENCRYPTION_KEY = module.secrets.secret_arns["encryption-key"]
    },
    # Conditional on the SAME variable that creates the secret and arms the cache's
    # auth check, so the three can never disagree: with auth off there is no
    # redis-url secret to reference, and REDIS_URL stays plain config.
    var.redis_auth_enabled ? {
      REDIS_URL = module.secrets.secret_arns["redis-url"]
    } : {},
  )

  log_group_names = module.data.log_group_names_by_key
  log_group_arns  = module.data.log_group_arns

  ecr_repository_arns = [
    local.ecr_repository_arns_by_key["api"],
    local.ecr_repository_arns_by_key["frontend"],
  ]

  documents_bucket_arn = module.documents.bucket_arn
  # The environment CMK, the same key the bucket's default encryption uses. Passing
  # it makes the task-role KMS statements render — api gets GenerateDataKey +
  # Decrypt, worker gets Decrypt only. Without it every upload fails with an opaque
  # AccessDenied from S3 rather than from KMS.
  documents_bucket_kms_key_arn = module.secrets.kms_key_arn
  secrets_kms_key_arn          = module.secrets.kms_key_arn

  bedrock_foundation_model_arns  = local.bedrock_foundation_model_arns
  bedrock_inference_profile_arns = local.bedrock_inference_profile_arns

  enable_container_insights = var.enable_container_insights
  enable_execute_command    = var.enable_execute_command
  enable_alb_access_logs    = var.enable_alb_access_logs
  alb_access_logs_bucket    = var.alb_access_logs_bucket

  worker_stop_timeout_seconds  = var.worker_stop_timeout_seconds
  deregistration_delay_seconds = var.deregistration_delay_seconds

  # --- TLS and authentication (phase 2) --- #
  enable_tls      = var.enable_tls
  certificate_arn = module.dns.certificate_arn
  ssl_policy      = var.ssl_policy
  domain_name     = var.domain_name

  enable_cognito                      = var.enable_cognito
  cognito_domain_prefix               = var.cognito_domain_prefix
  cognito_mfa_configuration           = var.cognito_mfa_configuration
  cognito_session_timeout_seconds     = var.cognito_session_timeout_seconds
  cognito_refresh_token_validity_days = var.cognito_refresh_token_validity_days
}
