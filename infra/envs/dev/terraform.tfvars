# Development environment values. NON-SECRET ONLY — this file is committed.
# No password, key, token, or connection string with credentials belongs here.

aws_account_id = "591554480818"
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
kms_deletion_window_days    = 7

# --- Registry -------------------------------------------------------------- #

# TWO repositories. The worker does NOT get its own: C1 established that the API
# and the worker run the same image with different commands.
ecr_repository_names     = ["mbai/api", "mbai/frontend"]
ecr_keep_last_images     = 10
ecr_untagged_expire_days = 7
# ⚠️ Should be false for staging — destroy should not silently discard image
# history there.
ecr_force_delete = true

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
redis_version   = "7.1"
redis_family    = "redis7"

# false → REDIS_URL is CONFIG (topology only), protected by security-group
# isolation. Transit encryption is on regardless, so the URL must still be
# rediss://...?ssl_cert_reqs=required. Setting this true creates a redis-url
# SECRET instead and requires applying a token out of band.
redis_auth_enabled = false

# --- Logs ------------------------------------------------------------------ #

log_retention_days = 30

# --- Budget ---------------------------------------------------------------- #

budget_limit_usd = 150
# ⚠️ Replace with the real address before applying — a budget alarm nobody
# receives is not an alarm.
budget_notification_email = "geet.thaker@gmail.com"

# --- External -------------------------------------------------------------- #

# Hand-created (C0). Looked up, never managed — it holds uploaded files and must
# survive every terraform destroy.
documents_bucket_name = "mbai-dev-documents-591554480818"
