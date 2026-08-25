# Environment inputs. Values live in terraform.tfvars (committed — non-secret
# only). No secret value may ever appear here or there.

variable "aws_account_id" {
  description = "Expected AWS account id. The guard in main.tf refuses to apply anywhere else."
  type        = string
}

variable "aws_region" {
  description = "Region for every resource in this environment."
  type        = string
}

variable "environment" {
  description = "Environment name — drives the Environment tag and the secret path."
  type        = string
}

variable "name_prefix" {
  description = "Prefix every resource name derives from."
  type        = string
}

# --- Network --------------------------------------------------------------- #

variable "vpc_cidr" {
  description = "VPC CIDR. ⚠️ Staging MUST differ from this if the two ever peer."
  type        = string
}

variable "availability_zones" {
  description = "AZs to spread subnets across. Two minimum (RDS subnet groups require it)."
  type        = list(string)
}

variable "enable_nat_gateway" {
  description = "Route private egress through a NAT gateway. See the result doc for the cost arithmetic."
  type        = bool
}

variable "enable_vpc_endpoints" {
  description = "Create VPC interface endpoints instead of / alongside NAT."
  type        = bool
}

variable "interface_endpoint_services" {
  description = "Short service names for interface endpoints; the region is interpolated by the module."
  type        = list(string)
}

# --- Secrets --------------------------------------------------------------- #

variable "secret_recovery_window_days" {
  description = "Secrets Manager recovery window. ⚠️ MUST BE 30 FOR STAGING — 0 only suits a throwaway environment."
  type        = number
}

variable "kms_deletion_window_days" {
  description = "Waiting period before a scheduled KMS key deletion completes (7-30). 7 = the AWS minimum, so orphaned keys clear as fast as allowed."
  type        = number
}

variable "kms_create_alias" {
  description = <<-EOT
    Create a friendly KMS alias. Console readability only — every consumer uses the
    ARN. ⚠️ An orphaned alias after destroy is what breaks rebuild; false here,
    true for long-lived environments.
  EOT
  type        = bool
}

# --- Registry -------------------------------------------------------------- #
#
# No ecr_* variables here. The registry is shared across environments and now
# lives in ../../shared with its own state and its own KMS key — see the note in
# main.tf where the module used to be instantiated.

# --- Database -------------------------------------------------------------- #

variable "postgres_version" {
  description = "PostgreSQL major version. Must match local (postgres:16-alpine)."
  type        = string
}

variable "postgres_family" {
  description = "RDS parameter-group family; must agree with postgres_version's major."
  type        = string
}

variable "rds_instance_class" {
  description = "Database instance class. Staging and production will be larger."
  type        = string
}

variable "rds_allocated_storage" {
  description = "Initial storage in GB."
  type        = number
}

variable "rds_max_allocated_storage" {
  description = "Storage autoscaling ceiling in GB."
  type        = number
}

variable "rds_multi_az" {
  description = "Standby in a second AZ. ⚠️ MUST BE true FOR STAGING."
  type        = bool
}

variable "rds_deletion_protection" {
  description = "Refuse to delete the database. ⚠️ MUST BE true FOR STAGING."
  type        = bool
}

variable "rds_skip_final_snapshot" {
  description = "Skip the final snapshot on delete. ⚠️ MUST BE false FOR STAGING."
  type        = bool
}

variable "rds_backup_retention_days" {
  description = "Automated backup retention in days."
  type        = number
}

variable "rds_performance_insights_enabled" {
  description = "Enable Performance Insights. Free at 7-day retention; noisy for a throwaway environment."
  type        = bool
}

variable "database_name" {
  description = "Initial database name."
  type        = string
}

variable "database_username" {
  description = "Master username. The password is generated and never output."
  type        = string
}

# --- Cache ----------------------------------------------------------------- #

variable "redis_node_type" {
  description = "Cache node type."
  type        = string
}

variable "redis_version" {
  description = "Redis engine version. Must match local (redis:7-alpine)."
  type        = string
}

variable "redis_family" {
  description = "Cache parameter-group family; must agree with redis_version's major."
  type        = string
}

variable "redis_auth_enabled" {
  description = <<-EOT
    Require an AUTH token on the cache. Drives BOTH the data module and whether a
    redis-url SECRET is created — wired from this single variable so the two can
    never disagree.
  EOT
  type        = bool
}

# --- Logs ------------------------------------------------------------------ #

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
}

# --- Budget ---------------------------------------------------------------- #

variable "budget_limit_usd" {
  description = "Monthly cost budget in USD."
  type        = number
}

variable "budget_notification_email" {
  description = "Address notified at 80% actual and 100% forecast. Never hardcoded in a .tf file."
  type        = string
}

# --- External, not managed here -------------------------------------------- #

variable "documents_bucket_name" {
  description = <<-EOT
    The hand-created documents bucket (C0). Looked up with a data source, NEVER
    managed: it holds uploaded files and must survive every terraform destroy.
  EOT
  type        = string
}

# --- Compute (C3) ----------------------------------------------------------- #

variable "ecr_repository_names" {
  description = <<-EOT
    Map of service key to the ECR repository NAME in the shared registry.

    Looked up with `data.aws_ecr_repository` rather than read out of shared's state
    — see the note in main.tf.
  EOT
  type        = map(string)
}

variable "image_tag" {
  description = <<-EOT
    Image tag the task definitions reference. Repositories are IMMUTABLE, so a tag
    always means the same bytes.

    ⚠️ Must already be pushed. A task definition referencing a missing tag fails at
    launch with CannotPullContainerError, visible only in the service events.
  EOT
  type        = string
}

variable "cpu_architecture" {
  description = <<-EOT
    Must match the architecture of the pushed images. ⚠️ A mismatch fails with
    `exec format error`, visible only in the CloudWatch log stream.
  EOT
  type        = string
}

variable "api_cpu" {
  description = "API task CPU units."
  type        = number
}

variable "api_memory" {
  description = "API task memory (MiB)."
  type        = number
}

variable "worker_cpu" {
  description = "Worker task CPU units."
  type        = number
}

variable "worker_memory" {
  description = "Worker task memory (MiB). Larger than the API's — extraction base64-encodes whole PDFs in memory."
  type        = number
}

variable "frontend_cpu" {
  description = "Frontend task CPU units."
  type        = number
}

variable "frontend_memory" {
  description = "Frontend task memory (MiB)."
  type        = number
}

variable "api_desired_count" {
  description = "API task count."
  type        = number
}

variable "frontend_desired_count" {
  description = "Frontend task count."
  type        = number
}

variable "worker_desired_count" {
  description = "Worker task count. Parallel jobs = worker_desired_count x worker_concurrency."
  type        = number
}

variable "worker_concurrency" {
  description = "Celery children per worker task — jobs running at once inside ONE task."
  type        = number
}

variable "enable_container_insights" {
  description = "Container Insights on the ECS cluster. Costs money per metric."
  type        = bool
}

variable "enable_execute_command" {
  description = "ECS Exec. ⚠️ A production access path — grants a shell in a task holding borrower data."
  type        = bool
}

variable "enable_alb_access_logs" {
  description = "Write ALB access logs to S3."
  type        = bool
}

variable "alb_access_logs_bucket" {
  description = "Bucket for ALB access logs; ignored when enable_alb_access_logs is false."
  type        = string
}

variable "worker_stop_timeout_seconds" {
  description = "SIGTERM-to-SIGKILL grace for the worker. 120 is the Fargate maximum."
  type        = number
}

variable "deregistration_delay_seconds" {
  description = "Target group draining period; the AWS default of 300s makes every deploy slow."
  type        = number
}

variable "bedrock_rpm_budget" {
  description = <<-EOT
    The requests-per-minute this ENVIRONMENT may spend against Bedrock, in total.
    main.tf divides it by worker_desired_count x worker_concurrency to get the
    per-process pacing value (LP-629).

    This account's granted quota is 10 RPM, so the budget must stay <= 8. Dev cannot
    be tuned by copying staging — its cap is set by the quota, not by taste.
  EOT
  type        = number
}

variable "bedrock_model_ids" {
  description = "Map of tier key to the `us.` inference-profile id the application sends."
  type        = map(string)
}

variable "bedrock_profile_regions" {
  description = <<-EOT
    Regions a `us.` cross-region inference profile may route to.

    ⚠️ VERIFIED, and wider than it looks: `aws bedrock get-inference-profile` shows
    the us. profiles routing to us-east-1, us-east-2 AND us-west-2. The IAM policy
    needs the foundation-model ARN in every one — omitting a region produces an
    INTERMITTENT AccessDeniedException that only fires when Bedrock routes there.
  EOT
  type        = list(string)
}

variable "documents_bucket_kms_key_arn" {
  description = <<-EOT
    CMK protecting the documents bucket, or null when it uses SSE-S3.

    ⚠️ PENDING VERIFICATION — the C3 author could not read the bucket's encryption
    configuration (the available role lacks s3:GetEncryptionConfiguration). Confirm
    with:
      aws s3api get-bucket-encryption --bucket <documents bucket>
    If it returns aws:kms, set this to that key ARN. If SSE-S3, leave it null.
  EOT
  type        = string
}

variable "cors_allowed_origins" {
  description = <<-EOT
    Origins the API accepts, as a LIST — Terraform jsonencodes it.

    ⚠️ The application parses this env var as JSON (pydantic-settings complex type).
    A bare "http://host" string raises SettingsError and the app REFUSES TO START,
    verified against the installed pydantic-settings. So this fails loudly rather
    than silently, unlike most of the config traps here.

    ⚠️ CHICKEN AND EGG: the real value is the ALB's DNS name, which does not exist
    until after the first apply. It cannot be wired from module.compute.alb_dns_name
    because that would make the compute module depend on its own output. In practice
    the frontend and API share one ALB origin, so browser calls are SAME-ORIGIN and
    CORS is not on the critical path until C4 introduces a separate domain.
    Update this after the first apply, or at C4.
  EOT
  type        = list(string)
}
