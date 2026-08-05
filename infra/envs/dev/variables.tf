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
