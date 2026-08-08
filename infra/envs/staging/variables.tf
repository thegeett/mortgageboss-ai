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
  description = "Standby in a second AZ. Single-AZ is accepted here (see terraform.tfvars, which sets false); production must be true."
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

# --- Documents ------------------------------------------------------------- #

variable "documents_bucket_name" {
  description = <<-EOT
    Name of the documents bucket, CREATED AND MANAGED by `module.documents`.

    ⚠️ This description used to say the bucket was hand-made and "NEVER managed —
    must survive every terraform destroy". C4 changed that: Terraform now creates it
    (main.tf), CMK-encrypted, because it holds real borrower files and a CMK gives a
    separate audit trail and a revocation lever.

    It survives a destroy because the module sets `prevent_destroy`, NOT because it
    is outside Terraform. The bucket holds the only copy of every uploaded document —
    the database stores keys, not content.
  EOT
  type        = string
}

# --- Compute (C3) ----------------------------------------------------------- #

variable "ecr_registry_account_id" {
  description = <<-EOT
    Account holding the SHARED ECR registry — the tooling account, NOT this
    environment's `aws_account_id`.

    The image URLs and repository ARNs are assembled from this rather than read with
    `data.aws_ecr_repository`, because a data source resolves through this
    environment's provider and would look the repositories up in the wrong account.

    ⚠️ Cross-account pull also needs a repository policy and `kms:Decrypt` on the
    registry's key, both granted by `infra/shared` via `ecr_pull_account_ids`.
  EOT
  type        = string
}

variable "ecr_repository_names" {
  description = <<-EOT
    Map of service key to the ECR repository NAME in the shared registry.

    The name is the contract between this state and shared's — deliberately not
    `terraform_remote_state`, which would read the whole shared state and couple to
    its output names. See the note in main.tf.
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

variable "desired_count" {
  description = "Task count per service. ⚠️ Raising the worker's requires dividing ai_requests_per_minute_bedrock by it."
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

variable "ai_requests_per_minute_bedrock" {
  description = <<-EOT
    Client-side pacing for Bedrock. ⚠️ PER PROCESS — N worker tasks pace at N x this
    value. The account quota is 10 RPM, so at desired_count = 1 this must be <= 8.
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
    CMK protecting the documents bucket. Null (the default) means "use this
    environment's own CMK", which is what `module.documents` receives.

    The bucket is now created by Terraform with SSE-KMS, so the earlier "PENDING
    VERIFICATION / confirm with get-bucket-encryption" note is obsolete — the
    encryption is declared here, not discovered.

    Override only to protect documents with a key from another state (e.g. a
    separate compliance-owned CMK). ⚠️ Whatever key is used must also be the one the
    application sends as S3_KMS_KEY_ID, or every upload fails against the bucket's
    default encryption.
  EOT
  type        = string
  default     = null
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

# --- DNS / TLS / auth (C4) --------------------------------------------------- #

variable "domain_name" {
  description = <<-EOT
    Public domain this environment is served on, e.g. "sub.example.com".

    A DELEGATED SUBDOMAIN — the apex stays with the existing registrar and is never
    delegated to AWS. Also the basis for the Cognito callback URL, which is why it
    must be known before anything is created.
  EOT
  type        = string
}

variable "enable_tls" {
  description = <<-EOT
    ⚠️ THE PHASE GATE. false for phase 1, true for phase 2.

    Phase 1 creates the hosted zone and emits its four nameservers. Those must then
    be entered at the registrar BY HAND and allowed to propagate. Only then does
    phase 2 (this set to true) create the ACM certificate, the HTTPS listener, the
    port-80 redirect, and Cognito.

    Flipping it early is not destructive — ACM sits in PENDING_VALIDATION until the
    validation timeout expires and the apply fails.
  EOT
  type        = bool
}

variable "ssl_policy" {
  description = "ALB TLS security policy."
  type        = string
}

variable "enable_cognito" {
  description = "Authenticate every request at the ALB. ⚠️ Requires enable_tls."
  type        = bool
}

variable "cognito_domain_prefix" {
  description = "Prefix for the Cognito hosted UI domain. Globally unique across AWS."
  type        = string
}

variable "cognito_mfa_configuration" {
  description = "OFF | OPTIONAL | ON. OPTIONAL initially — ON before any user exists locks out the first account."
  type        = string
}

variable "cognito_session_timeout_seconds" {
  description = "ALB auth session lifetime. ⚠️ Long on purpose — see the compute module README."
  type        = number
}

variable "cognito_refresh_token_validity_days" {
  description = "Refresh token lifetime in days. Must exceed the session timeout."
  type        = number
}

variable "endpoint_availability_zones" {
  description = <<-EOT
    AZs receiving interface endpoints, and therefore the AZs the ECS tasks run in.

    One AZ roughly halves endpoint cost. The two-AZ subnet group RDS requires is a
    constraint on the subnet GROUP, not on where anything runs — the second subnet
    exists and stays empty.
  EOT
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = <<-EOT
    Optional IP allowlist for the load balancer. Empty means no restriction.

    Offered as a LEVER, not a default. A home IP is dynamic, so an allowlist here
    would eventually lock out a legitimate user with no obvious cause — a bad
    trade when Cognito already gates every request.
  EOT
  type        = list(string)
  default     = []
}
