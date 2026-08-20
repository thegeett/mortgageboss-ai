# Staging values. NON-SECRET ONLY — this file is committed.
#
# This is the first and only DEPLOYED environment. ../dev is a reference template
# that is never applied (local development runs against Docker Compose and calls
# Bedrock from the laptop), so every safety flag that dev leaves off is on here.

aws_account_id = "058190633983"
aws_region     = "us-east-1"
environment    = "staging"
name_prefix    = "mbai-staging"

# --- Network ----------------------------------------------------------------- #

# ⚠️ MUST differ from the dev template's 10.20.0.0/16 — identical ranges cannot be
# peered, and the two may need to be.
vpc_cidr           = "10.30.0.0/16"
availability_zones = ["us-east-1a", "us-east-1b"]

# NO NAT. All egress goes through interface endpoints, so task traffic never
# traverses the public internet — the compliance property that justified moving
# inference to Bedrock in the first place.
enable_nat_gateway   = false
enable_vpc_endpoints = true

# ⚠️ ONE AZ. Interface endpoints are ENIs billed per endpoint PER AZ: five across
# two AZs is ~$73/month, in one ~$36.50. Acceptable only because there is no
# redundancy to lose — desired_count is 1 and RDS is single-AZ. The ECS tasks are
# pinned to this same AZ (see main.tf); tasks and endpoints must move together.
# Production sets two.
endpoint_availability_zones = ["us-east-1a"]

# bedrock-runtime is the endpoint the application actually uses — it calls Bedrock
# through `us.` inference profiles. com.amazonaws.us-east-1.bedrock-mantle also
# exists in this region but nothing uses it.
# ⚠️ With no NAT, anything NOT in this list is unreachable, and a missed dependency
# HANGS rather than failing. See the outbound audit in the result doc.
interface_endpoint_services = [
  "ecr.api",
  "ecr.dkr",
  "logs",
  "secretsmanager",
  "bedrock-runtime",
]

# --- DNS / TLS / auth -------------------------------------------------------- #

domain_name = "staging.mortgageboss.ai"

# ⚠️ THE PHASE GATE — false for phase 1, true for phase 2.
#
#   phase 1  (false): creates the hosted zone, outputs four nameservers
#   MANUAL          : enter those NS records at the registrar, wait for propagation
#                     verify: dig +short NS staging.mortgageboss.ai
#   phase 2  (true) : ACM certificate, HTTPS listener, port-80 redirect, Cognito
#
# Flipping early is not destructive; ACM just sits in PENDING_VALIDATION until the
# apply times out.
enable_tls = true

# TLS 1.3 with a 1.2 floor.
ssl_policy = "ELBSecurityPolicy-TLS13-1-2-2021-06"

# Independent of the application's own JWT auth, and that is the point: this is the
# environment where an application auth bug would first appear, so an unauthenticated
# request must never reach a task.
#
# ⚠️ THIS FLAG MOVES WITH enable_tls ABOVE — flip BOTH in phase 2, neither in
# phase 1. An ALB cannot attach authenticate-cognito to an HTTP listener, so
# terraform_data.auth_guard (modules/compute/alb.tf) fails the plan on the pair
# (cognito = true, tls = false) rather than letting the environment come up with no
# authentication while appearing configured.
#
# It shipped as `true` alongside `enable_tls = false`, which meant the guard fired
# on the very first phase-1 plan and NOTHING could be created. The guard was right;
# the value was wrong.
enable_cognito        = true # ⚠️ phase 2: set true at the same time as enable_tls
cognito_domain_prefix = "mbai-staging-auth"

# OPTIONAL, not ON: enforcing MFA before any user exists locks out the first
# admin-created account. ⚠️ Turn ON once users are enrolled — it is on the
# pre-handover checklist.
cognito_mfa_configuration = "OPTIONAL"

# 7 days, deliberately long. A session expiring mid-use turns an in-flight fetch()
# into a 302 toward a login page that browser JavaScript cannot follow, so the app
# fails in ways that look like application bugs. Long sessions expire BETWEEN
# visits, not during one.
cognito_session_timeout_seconds = 604800

# Must exceed the session timeout or the ALB cannot silently renew.
cognito_refresh_token_validity_days = 30

# Empty = no IP restriction. Offered as a lever, not a default: a home IP is
# dynamic, so this would eventually lock out a legitimate user for no visible
# reason, and Cognito already gates every request.
allowed_cidr_blocks = []

# --- Secrets ------------------------------------------------------------------ #

# 30, NOT 0. This environment is not destroy-and-rebuild; a mistaken destroy must
# stay recoverable.
secret_recovery_window_days = 30
kms_deletion_window_days    = 30

# Long-lived, so the console readability is worth the rebuild friction an orphaned
# alias causes (ADR-365).
kms_create_alias = true

# --- Database ----------------------------------------------------------------- #

postgres_version = "16"
postgres_family  = "postgres16"

rds_instance_class        = "db.t4g.small"
rds_allocated_storage     = 50
rds_max_allocated_storage = 500
rds_backup_retention_days = 30

# ⚠️ THE FLAGS DEV DELIBERATELY LEFT OFF. This environment holds real borrower NPI.
rds_multi_az            = false # revisit for production
rds_deletion_protection = true
rds_skip_final_snapshot = false

rds_performance_insights_enabled = true

database_name     = "mortgageboss"
database_username = "mbai_admin"

# --- Cache -------------------------------------------------------------------- #

redis_node_type = "cache.t4g.small"
redis_version   = "7.1"
redis_family    = "redis7"

# true: makes REDIS_URL a credential and creates the redis-url secret. Defence in
# depth alongside security-group isolation.
redis_auth_enabled = true

ecr_repository_names = {
  api      = "mbai/api"
  frontend = "mbai/frontend"
}

# ⚠️ The frontend image for THIS tag must be built with
# NEXT_PUBLIC_API_URL=https://staging.mortgageboss.ai — it is inlined at BUILD time
# and cannot be set as a task environment variable. See the result doc.
#
# ⚠️ OWNED BY `./scripts/deploy staging deploy` from here on. It derives the tag
# from git (`staging-<short sha>`), builds those exact bytes, and rewrites this
# line. Editing it by hand re-opens the failure it closes: a tag bumped without a
# build, or a build without a bump, both of which produced CannotPullContainerError.
image_tag = "staging-532b9c8"

# Branches the deploy stage will ship FROM. Read by scripts/deploy, not by any
# module. Several worktrees on this machine sit on different branches and
# `docker build` ships whatever is checked out where it runs — see the variable's
# description in variables.tf.
allowed_deploy_branches = ["bedrock_integration", "bedrock_integration_with_rules_staging"]

# Verified in C3: the images are arm64. Fargate defaults to X86_64 and the mismatch
# fails with `exec format error`, visible only in the CloudWatch log stream.
cpu_architecture = "ARM64"

api_cpu       = 512
api_memory    = 1024
worker_cpu    = 1024
worker_memory = 2048

frontend_cpu    = 256
frontend_memory = 512

desired_count = 1

enable_container_insights = false

# ⚠️ OFF — reconsidered from dev, deliberately. ECS Exec is a shell inside a task
# holding decrypted secrets and borrower NPI, not a debugging convenience. It can
# be flipped on for a specific session and back off; doing so requires a service
# update, and that friction is the point. See the result doc.
enable_execute_command = false

enable_alb_access_logs = false
alb_access_logs_bucket = ""

worker_stop_timeout_seconds  = 120
deregistration_delay_seconds = 30

# Client-side pacing for Bedrock. NOT the quota — a backstop under it.
#
# The granted quota in this account (058190633983, us-east-1) is 10,000 RPM on
# BOTH models the application uses, verified from Service Quotas:
#   Cross-region model inference requests per minute for Anthropic Claude Haiku 4.5      10000
#   Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1  10000
# `us.`-prefixed inference profile ids consume the CROSS-REGION family above. Two
# neighbouring quotas are decoys: the "Global cross-region" family is still 10, and
# "Sonnet 4.5 V1 1M Context Length" is 1 — neither is used here, and a model id
# gaining a `global.` prefix or the 1M variant would silently drop the ceiling by
# three orders of magnitude.
#
# 2000 is ~20% of 10,000. The headroom is deliberate: a REJECTED request still
# counts against the quota, so pacing at the ceiling turns one burst of throttling
# into a self-sustaining one.
#
# ⚠️ THE LIMITER IS PER PROCESS, NOT PER ENVIRONMENT. At desired_count = 1 this IS
# the effective rate; at N worker tasks the effective rate is N x this value.
# Raising the worker count REQUIRES dividing this by the new count — scaling the
# worker otherwise multiplies the request rate silently.
#
# Kept rather than unset. At 10,000 RPM it is mostly insurance, but a runaway loop
# is far cheaper to notice at 2000 than unbounded.
#
# Was 8, tuned for the old ceiling of 10. At 10,000 that pacing made the limiter
# the constraint rather than the backstop: a full loan file spent minutes waiting
# for no reason.
ai_requests_per_minute_bedrock = 2000

bedrock_model_ids = {
  classification = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  extraction     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  reasoning      = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

# Verified in C3: the `us.` profiles route to THREE regions. A single-region list
# under-grants and fails INTERMITTENTLY, only when Bedrock routes elsewhere.
bedrock_profile_regions = ["us-east-1", "us-east-2", "us-west-2"]

# --- Storage ------------------------------------------------------------------ #

# Created by Terraform here, CMK-encrypted — unlike the dev template's hand-made,
# SSE-S3 bucket. Starts EMPTY: dev documents are development artifacts and have no
# place in an environment holding borrower NPI.
documents_bucket_name = "mbai-staging-documents-058190633983"

# Wired from the environment CMK in main.tf, so the task-role KMS statements render.
documents_bucket_kms_key_arn = null

# --- Logs / budget ------------------------------------------------------------ #

log_retention_days = 30

# 300, not dev's 150 — that would fire immediately against this environment's cost.
budget_limit_usd          = 300
budget_notification_email = "budget@mortgageboss.ai"

# --- Frontend ----------------------------------------------------------------- #

# ⚠️ Must be the real origin, and the app parses this as JSON — a bare string
# raises SettingsError and the app refuses to start (verified in C3), so this one
# fails loudly rather than silently.
cors_allowed_origins = ["https://staging.mortgageboss.ai"]

# --- Registry (moved in from the dissolved shared state) ---------------------- #

# Ordinary retention tier. Promoted tags are protected separately below, so a busy
# pipeline burning through this count cannot evict the image staging is running.
ecr_keep_last_images     = 30
ecr_untagged_expire_days = 7

ecr_protected_tag_prefixes     = ["staging-", "prod-", "release-"]
ecr_keep_last_protected_images = 20

# false, deliberately. A destroy here would discard the image history, which is not
# something a plan should be able to do quietly.
ecr_force_delete = false

# ⚠️ false BECAUSE IT CANNOT SUCCEED HERE, not because it is unwanted.
#
# Cost Explorer tag activation is MANAGEMENT-ACCOUNT ONLY. 058190633983 is a member
# account in the organization, so the C5 phase-1 apply failed on it with:
#   AccessDeniedException: Failed to update Cost Allocation Tag: Linked account
#   doesn't have access to cost allocation tags.
# No permission grant inside this account can fix that — it is an organizational
# boundary. Leave this false in every member-account environment.
#
# ⚠️ THE REQUIREMENT DOES NOT GO AWAY. AWS Budgets matches NOTHING until
# `Environment` is active as a cost allocation tag, so the $300 budget above
# reports $0 forever and never fires while looking correctly configured in the
# console. That is a silent failure, and turning this flag off does not fix it —
# it only stops Terraform from failing on something it cannot do.
#
# MANUAL, ONE TIME, FROM THE MANAGEMENT ACCOUNT:
#   Billing -> Cost allocation tags -> user-defined -> Environment -> Activate
# Up to 24 hours before it begins reporting. The budget alarm is INERT until then.
# Tracked in infra/README.md (apply order) and the C5 pre-handover checklist.
activate_environment_cost_allocation_tag = false
