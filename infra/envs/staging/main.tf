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
  kms_key_arn = module.secrets.kms_key_arn
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

# --------------------------------------------------------------------------- #
# Compute (C3) — ECS cluster, three Fargate services, ALB, per-task IAM
# --------------------------------------------------------------------------- #

# The images live in the SHARED registry, which is a THIRD state file.
#
# Read with `data.aws_ecr_repository`, deliberately NOT `terraform_remote_state`:
#
#   * terraform_remote_state reads the ENTIRE shared state, so this environment
#     would need s3:GetObject on that state object — and would then hold every
#     attribute of every resource in it, not just the two values wanted here.
#   * It also couples to shared's OUTPUT NAMES. Renaming an output there would
#     break every environment, turning a local refactor into a fleet-wide one.
#   * The repository NAME is the real contract between the two states, and it is
#     already a variable. Looking it up by name depends on the AWS resource rather
#     than on how another state file happens to be shaped.
#
# Trade-off accepted: no plan-time ordering. If shared has not been applied, this
# fails with a clear "repository not found" rather than an implicit dependency.
data "aws_ecr_repository" "api" {
  name = var.ecr_repository_names["api"]
}

data "aws_ecr_repository" "frontend" {
  name = var.ecr_repository_names["frontend"]
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

  api_image        = "${data.aws_ecr_repository.api.repository_url}:${var.image_tag}"
  frontend_image   = "${data.aws_ecr_repository.frontend.repository_url}:${var.image_tag}"
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
  environment_variables = {
    ENVIRONMENT     = var.environment
    LOG_FORMAT      = "json"
    STORAGE_BACKEND = "s3"
    S3_BUCKET       = var.documents_bucket_name
    S3_REGION       = var.aws_region

    # ⚠️ REQUIRED for a CMK-encrypted bucket. app/storage/s3.py sends
    # ServerSideEncryption=aws:kms + SSEKMSKeyId ONLY when this is set; unset, it
    # sends AES256 (SSE-S3) instead, which conflicts with the bucket's KMS default.
    S3_KMS_KEY_ID        = module.secrets.kms_key_arn
    CORS_ALLOWED_ORIGINS = jsonencode(var.cors_allowed_origins)
    AI_PROVIDER          = "bedrock"
    BEDROCK_REGION       = var.aws_region

    BEDROCK_MODEL_CLASSIFICATION = var.bedrock_model_ids["classification"]
    BEDROCK_MODEL_EXTRACTION     = var.bedrock_model_ids["extraction"]
    BEDROCK_MODEL_REASONING      = var.bedrock_model_ids["reasoning"]

    AI_REQUESTS_PER_MINUTE_BEDROCK = tostring(var.ai_requests_per_minute_bedrock)

    # REDIS_URL is CONFIG rather than a secret while the cache has no AUTH token:
    # the URL is topology only. ⚠️ Both parts of this value matter — transit
    # encryption makes rediss:// mandatory, and without ?ssl_cert_reqs=required
    # redis-py verifies the certificate while kombu resolves to CERT_NONE.
    REDIS_URL = "rediss://${module.data.redis_primary_endpoint}:6379/0?ssl_cert_reqs=required"
  }

  frontend_environment_variables = {
    NODE_ENV = "production"
    # NEXT_PUBLIC_API_URL is absent on purpose — it is inlined into the JavaScript
    # bundle at BUILD time and is not read at runtime (C1). Setting it here would
    # do nothing while appearing to work.
  }

  # DATABASE_URL carries the master password; JWT and encryption keys are secrets
  # by definition. Injected by the ECS agent via the EXECUTION role, so no task
  # role needs secretsmanager:GetSecretValue.
  secret_arns = {
    DATABASE_URL   = module.secrets.secret_arns["database-url"]
    JWT_SECRET_KEY = module.secrets.secret_arns["jwt-secret-key"]
    ENCRYPTION_KEY = module.secrets.secret_arns["encryption-key"]
  }

  log_group_names = module.data.log_group_names_by_key
  log_group_arns  = module.data.log_group_arns

  ecr_repository_arns = [
    data.aws_ecr_repository.api.arn,
    data.aws_ecr_repository.frontend.arn,
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
