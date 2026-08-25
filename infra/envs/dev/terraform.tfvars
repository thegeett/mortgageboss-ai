# Development environment values. NON-SECRET ONLY — this file is committed.
# No password, key, token, or connection string with credentials belongs here.

# ⚠️ PLACEHOLDER. This template is never applied, and the account it once named
# is no longer used by this project. Replace before using it as a starting point.
aws_account_id = "000000000000"
aws_region     = "us-east-1"
environment    = "dev"
name_prefix    = "mbai-dev"

# --- Network --------------------------------------------------------------- #

# ⚠️ Staging MUST use a different CIDR (e.g. 10.30.0.0/16) — identical ranges
# cannot be peered, and this environment and staging may well need to be.
vpc_cidr           = "10.20.0.0/16"
availability_zones = ["us-east-1a", "us-east-1b"]

# NAT rather than interface endpoints, for this environment only.
#
#   NAT gateway (1)               $32.85/mo + $0.045/GB
#   Interface endpoints x5, 2 AZ  $73.00/mo + $0.010/GB
#   Interface endpoints x5, 1 AZ  $36.50/mo + $0.010/GB
#
# Endpoints are priced PER AZ ($0.01/hr each), so five of them across two AZs is
# 2.2x a NAT gateway. At this environment's traffic the data-transfer difference
# is noise: endpoints only overtake NAT above ~1,147 GB/month of egress.
#
# So for a throwaway environment holding NO borrower data, NAT is both cheaper and
# simpler to debug. STAGING SHOULD FLIP THIS — there the point is not cost but
# that task egress never touches the public internet, which is the whole reason
# inference was moved to Bedrock. See docs/tickets/C2-terraform-result.md.
enable_nat_gateway   = true
enable_vpc_endpoints = false

# Consumed only when enable_vpc_endpoints = true. Region is interpolated by the
# module, so these are short names.
# ⚠️ bedrock-runtime has NOT been verified to exist as an interface endpoint in
# this region — see the result doc. Verify before flipping endpoints on.
interface_endpoint_services = [
  "ecr.api",
  "ecr.dkr",
  "logs",
  "secretsmanager",
  "bedrock-runtime",
]

# --- Secrets --------------------------------------------------------------- #

# 0 = delete immediately. A non-zero window leaves the NAME RESERVED, so
# destroy-then-apply fails on a conflict — fatal for a destroy-and-rebuild
# environment. ⚠️ STAGING MUST USE 30.
secret_recovery_window_days = 0

# 7 = the AWS minimum. A destroy leaves the key pending deletion for this long
# (~$1/month each while it lingers); the minimum clears orphans as fast as AWS
# allows. ⚠️ Staging uses 30.
kms_deletion_window_days = 7

# NO alias for this environment. `terraform destroy` schedules the key but leaves
# the ALIAS orphaned (hashicorp/terraform-provider-aws#35161), and the orphaned
# alias — not the key — is what makes the next apply fail with
# AlreadyExistsException. Skipping it removes the only manual step from
# destroy-and-rebuild. Nothing functional depends on it; every consumer uses the
# key ARN. ⚠️ Staging sets this true.
kms_create_alias = false

# --- Registry -------------------------------------------------------------- #
#
# Configured in ../../shared/terraform.tfvars, not here. The registry is shared
# across environments, so it cannot be owned by this environment's state — this
# environment is destroy-and-rebuild, and that destroy would have taken every
# other environment's images with it.

# --- Database -------------------------------------------------------------- #

# Major-only on purpose: AWS picks the current minor, so nothing goes stale.
# Local runs postgres:16-alpine.
postgres_version = "16"
postgres_family  = "postgres16"

rds_instance_class        = "db.t4g.micro"
rds_allocated_storage     = 20
rds_max_allocated_storage = 100
rds_backup_retention_days = 7

# ⚠️ ALL THREE MUST FLIP FOR STAGING: multi_az true, deletion_protection true,
# skip_final_snapshot false.
rds_multi_az            = false
rds_deletion_protection = false
rds_skip_final_snapshot = true

rds_performance_insights_enabled = false

database_name     = "mortgageboss"
database_username = "mbai_admin"

# --- Cache ----------------------------------------------------------------- #

redis_node_type = "cache.t4g.micro"
# CONFIRMED correct: ElastiCache for Redis 7.1 has been GA in all regions since
# November 2023 and remains the highest Redis OSS version ElastiCache supports.
redis_version = "7.1"
redis_family  = "redis7"

# false → REDIS_URL is CONFIG (topology only), protected by security-group
# isolation. Transit encryption is on regardless, so the URL must still be
# rediss://...?ssl_cert_reqs=required. Setting this true creates a redis-url
# SECRET instead and requires applying a token out of band.
redis_auth_enabled = false

# --- Logs ------------------------------------------------------------------ #

log_retention_days = 30

# --- Budget ---------------------------------------------------------------- #

budget_limit_usd = 150
# ⚠️ This mailbox must actually EXIST. AWS Budgets does not confirm an email
# subscriber the way SNS does — if it bounces, the alert is silently dead and
# nothing in Terraform or the console will say so. Send yourself a test mail before
# relying on it.
#
# The other half of the alarm is the cost-allocation tag: the cost_filter in main.tf
# matches nothing until `Environment` is activated account-wide by ../../shared.
budget_notification_email = "budget@mortgageboss.ai"

# --- External -------------------------------------------------------------- #

# Hand-created (C0). Looked up, never managed — it holds uploaded files and must
# survive every terraform destroy.
documents_bucket_name = "mbai-dev-documents-000000000000" # placeholder — see above

# --- Compute (C3) ----------------------------------------------------------- #

# Repository NAMES in the shared registry, looked up by data.aws_ecr_repository.
ecr_repository_names = {
  api      = "mbai/api"
  frontend = "mbai/frontend"
}

# ⚠️ Must already be pushed. Repositories are IMMUTABLE, so a tag is a fixed set
# of bytes; a missing tag fails at launch with CannotPullContainerError.
image_tag = "latest"

# ⚠️ VERIFIED EMPIRICALLY, not assumed. The C1 images were built on Apple Silicon:
#   docker image inspect mbai-api:test      --format '{{.Architecture}}'  -> arm64
#   docker image inspect mbai-frontend:test --format '{{.Architecture}}'  -> arm64
# and the live worker container reports `uname -m` = aarch64. Fargate defaults to
# X86_64, and the mismatch fails with `exec format error` — a message that appears
# ONLY in the CloudWatch log stream, never in the ECS console's service events.
cpu_architecture = "ARM64"

api_cpu    = 512
api_memory = 1024

# Deliberately the largest: extraction holds a whole PDF in memory while base64
# encoding it, against a 50 MB upload cap.
worker_cpu    = 1024
worker_memory = 2048

frontend_cpu    = 256
frontend_memory = 512

# One of each. There is NO autoscaling — see the result doc.
api_desired_count      = 1
frontend_desired_count = 1

# LP-629 — 1 task x 2 children = 2 parallel jobs. Lower than staging's 4 because the
# account's Bedrock quota is 10 RPM total: dev's cap is set by the quota, not by taste.
worker_desired_count = 1
worker_concurrency   = 2

# Costs money per metric; off for a cost-sensitive throwaway environment.
enable_container_insights = false

# Fargate has no SSH, and several failure modes here produce no log line at all.
# ⚠️ This grants a shell inside a task. Fine here; reconsider for staging, which
# holds real borrower data.
enable_execute_command = true

enable_alb_access_logs = false
alb_access_logs_bucket = ""

# 120 is the Fargate maximum. Effective rather than decorative: `uv run` was
# verified to forward SIGTERM to its child, so Celery does get to finish its task.
worker_stop_timeout_seconds = 120

# The AWS default of 300s makes every deploy crawl.
deregistration_delay_seconds = 30

# LP-629 — the ENVIRONMENT's total budget; main.tf divides it across the worker slots
# (here 2, so each process paces at 4). The account is at 10 RPM, so 8 leaves headroom
# whatever the slot count is — which is the point of budgeting the total rather than
# the per-process value.
bedrock_rpm_budget = 8

# The `us.` cross-region inference profile ids the application sends.
bedrock_model_ids = {
  classification = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  extraction     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  reasoning      = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

# ⚠️ VERIFIED with `aws bedrock get-inference-profile`: the us. profiles route to
# THREE regions, not one. The IAM policy needs the foundation-model ARN in each —
# a us-east-1-only list fails intermittently, whenever Bedrock routes elsewhere.
bedrock_profile_regions = ["us-east-1", "us-east-2", "us-west-2"]

# ⚠️ PENDING VERIFICATION. Could not read the bucket's encryption configuration —
# the available role lacks s3:GetEncryptionConfiguration. null assumes SSE-S3, in
# which case no KMS statement is attached to the task roles. Confirm with:
#   aws s3api get-bucket-encryption --bucket <documents bucket>
# If it reports aws:kms, set this to that key's ARN or uploads fail with AccessDenied.
documents_bucket_kms_key_arn = null

# ⚠️ Placeholder until the ALB exists — its DNS name is not known before the first
# apply and cannot be self-referenced. The frontend and API share one ALB origin,
# so browser calls are same-origin and CORS is not on the critical path until C4.
cors_allowed_origins = ["http://localhost:3000"]
