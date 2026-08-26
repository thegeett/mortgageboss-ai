variable "name_prefix" {
  description = "Prefix for every resource name in this module."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "private_subnet_ids" {
  description = "Private subnets for the database and cache subnet groups."
  type        = list(string)
}

variable "rds_security_group_id" {
  description = "Security group permitting PostgreSQL from the ECS tasks only."
  type        = string
}

variable "redis_security_group_id" {
  description = "Security group permitting Redis from the ECS tasks only."
  type        = string
}

variable "kms_key_arn" {
  description = "Customer-managed key for storage encryption and log-group encryption."
  type        = string
}

# --------------------------------------------------------------------------- #
# RDS
# --------------------------------------------------------------------------- #

variable "postgres_version" {
  description = <<-EOT
    PostgreSQL engine version. MAJOR ONLY (e.g. "16") is deliberate and preferred:
    AWS then selects the current minor, and there is no pinned minor to go stale or
    to be rejected because it was retired between writing and applying.

    Local development runs postgres:16-alpine, so this must stay on 16.x.
  EOT
  type        = string
}

variable "postgres_family" {
  description = <<-EOT
    Parameter-group family, e.g. "postgres16". Must agree with postgres_version's
    major; AWS rejects a mismatch at apply time.
  EOT
  type        = string
}

variable "rds_instance_class" {
  description = "Database instance class."
  type        = string
}

variable "rds_allocated_storage" {
  description = "Initial storage in GB."
  type        = number
}

variable "rds_max_allocated_storage" {
  description = "Ceiling for storage autoscaling in GB."
  type        = number
}

variable "rds_multi_az" {
  description = "Run a standby in a second AZ. ⚠️ MUST BE true FOR STAGING AND PRODUCTION."
  type        = bool
}

variable "rds_deletion_protection" {
  description = "Refuse to delete the database. ⚠️ MUST BE true FOR STAGING AND PRODUCTION."
  type        = bool
}

variable "rds_skip_final_snapshot" {
  description = "Skip the final snapshot on delete. ⚠️ MUST BE false FOR STAGING AND PRODUCTION."
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
  description = "Master username. NOT a secret on its own; the password is generated and never leaves AWS."
  type        = string
}

# --------------------------------------------------------------------------- #
# ElastiCache
# --------------------------------------------------------------------------- #

variable "redis_node_type" {
  description = "Cache node type."
  type        = string
}

variable "redis_version" {
  description = "Redis engine version. Local development runs redis:7-alpine, so this must stay on 7.x."
  type        = string
}

variable "redis_family" {
  description = "Cache parameter-group family, e.g. \"redis7\". Must agree with redis_version's major."
  type        = string
}

variable "redis_auth_enabled" {
  description = <<-EOT
    Require an AUTH token on the cache.

    Consequences, both of which the environment must handle:
      * REDIS_URL becomes a CREDENTIAL (the token is embedded in it), so it must
        live in Secrets Manager rather than in environment[].
      * The URL scheme must be rediss:// — an AUTH token requires transit
        encryption, which is enabled unconditionally below.

    The token itself is NOT generated here. Like every other secret it is created
    out of band and written into the redis-url secret by the operator, so no
    credential ever enters Terraform state.
  EOT
  type        = bool
}

# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #

variable "log_group_names" {
  description = <<-EOT
    Full CloudWatch log group names to create, e.g. ["/ecs/<name_prefix>/api"].

    Created here rather than left to ECS auto-creation: an auto-created group
    defaults to NEVER EXPIRE, which accumulates cost and — more to the point —
    retains logs indefinitely with no deliberate policy.
  EOT
  type        = list(string)
}

variable "log_retention_days" {
  description = "Retention for every log group above."
  type        = number
}

variable "rds_backup_window" {
  description = <<-EOT
    Daily automated-backup window, UTC, "hh:mm-hh:mm". null lets AWS choose.

    Pin it on any environment that is stopped on a schedule: a stopped instance
    takes no automated backup, and an AWS-assigned window commonly falls in the
    early hours, which is exactly when such an environment is down. Must not
    overlap `rds_maintenance_window`.
  EOT
  type        = string
  default     = null
}

variable "rds_maintenance_window" {
  description = <<-EOT
    Weekly maintenance window, UTC, "ddd:hh:mm-ddd:hh:mm". null lets AWS choose.

    Same reasoning as `rds_backup_window`. Maintenance is not applied while an
    instance is stopped, so a window inside a nightly shutdown means pending
    updates accumulate until AWS's seven-day rule force-starts the instance and
    applies them unattended.
  EOT
  type        = string
  default     = null
}
