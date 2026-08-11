# Data — RDS PostgreSQL, ElastiCache Redis, and the CloudWatch log groups.
#
# Neither the database nor the cache is publicly reachable: both sit in private
# subnets with security groups that admit only the ECS tasks' group, and RDS
# additionally sets publicly_accessible = false.

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

# --------------------------------------------------------------------------- #
# RDS PostgreSQL
# --------------------------------------------------------------------------- #

resource "aws_db_subnet_group" "this" {
  name       = var.name_prefix
  subnet_ids = var.private_subnet_ids

  tags = merge(var.tags, { Name = var.name_prefix })
}

# rds.force_ssl = 1 — without it the server silently ACCEPTS an unencrypted
# connection. The default parameter group does not enforce TLS, and the security
# architecture assumes it.
#
# ⚠️ This makes the client's SSL behaviour load-bearing. See the module README:
# the URL must use `?ssl=require`, NOT the libpq spelling `?sslmode=require`,
# which crashes the application outright.
#
# name_prefix, NOT name: with create_before_destroy below, a static name makes the
# replacement impossible. Terraform would create the new group before destroying the
# old under the identical name and AWS returns DBParameterGroupAlreadyExists — so a
# postgres16 -> postgres17 family bump (the realistic replacement trigger) would fail
# mid-apply and stay blocked until someone hand-edited this file.
resource "aws_db_parameter_group" "this" {
  name_prefix = "${var.name_prefix}-"
  family      = var.postgres_family
  description = "${var.name_prefix} - forces TLS on every connection."

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# The master password is generated here and written NOWHERE by Terraform: it is
# not an output, not a secret version, and not a variable. It reaches the
# application only via the operator-assembled database-url secret.
#
# It IS in Terraform state — unavoidable for a random_password — which is why the
# state bucket is encrypted, versioned, and access-blocked. Retrieve it with
# `terraform output` only if you must (it is deliberately not exposed), or rotate
# it in the console and update the secret.
resource "random_password" "db" {
  length = 32

  # RDS rejects '/', '@', '"' and space in a master password. The set below is
  # narrowed further so the value is genuinely safe to paste into a URL without
  # percent-encoding, which is how the READMEs say it will be used.
  #
  # ⚠️ DO NOT re-add '#', '?' or '%'. This set previously included all three and
  # the app failed to boot roughly HALF the time:
  #
  #   * '#' and '?' are gen-delims — they terminate the URL authority component.
  #     `settings.database_url` is a Pydantic PostgresDsn, which rejects the DSN
  #     outright with the actively misleading "invalid port number". Over a
  #     32-char password, P(at least one) was about 55%.
  #   * '%' is worse because it is quiet: '%' + two hex digits validates fine and
  #     is then silently percent-decoded by SQLAlchemy ('ab%2Fcd' -> 'ab/cd'),
  #     so the password reaching Postgres is not the one in Secrets Manager and
  #     the only symptom is an authentication failure.
  #
  # What remains is sub-delims + unreserved punctuation, all legal unencoded in a
  # URL userinfo component (RFC 3986 §3.2.1). ':' is also excluded: it separates
  # user from password, so a password containing one splits the credential.
  #
  # ⚠️ CHANGING THIS SET ROTATES THE PASSWORD. override_special is ForceNew on
  # random_password — verified:
  #
  #   ~ override_special = "..." -> "..." # forces replacement
  #   Plan: 1 to add, 0 to change, 1 to destroy.
  #
  # aws_db_instance.password reads this value and RDS applies a MasterUserPassword
  # change IMMEDIATELY, regardless of apply_immediately. The database-url secret is
  # populated out of band, so it keeps the OLD password and every task starts
  # failing authentication with nothing in Terraform to explain it. On an existing
  # environment, re-populate that secret in the same maintenance step — see
  # "Migrating an already-applied environment" in infra/README.md.
  special          = true
  override_special = "!$&*()-_=+,.;~"
}

resource "aws_db_instance" "this" {
  identifier = var.name_prefix

  engine         = "postgres"
  engine_version = var.postgres_version
  instance_class = var.rds_instance_class

  # With a major-only engine_version, AWS picks the current minor. Allowing minor
  # upgrades keeps that true over time instead of freezing on first apply.
  auto_minor_version_upgrade = true

  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = var.kms_key_arn

  db_name  = var.database_name
  username = var.database_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.this.name
  parameter_group_name   = aws_db_parameter_group.this.name
  vpc_security_group_ids = [var.rds_security_group_id]

  # Never reachable from the internet.
  publicly_accessible = false
  multi_az            = var.rds_multi_az

  backup_retention_period = var.rds_backup_retention_days
  deletion_protection     = var.rds_deletion_protection
  skip_final_snapshot     = var.rds_skip_final_snapshot

  # A final snapshot needs a name; AWS rejects the pair (skip=false, identifier
  # unset). Only set it when a snapshot will actually be taken.
  final_snapshot_identifier = var.rds_skip_final_snapshot ? null : "${var.name_prefix}-final"

  performance_insights_enabled = var.rds_performance_insights_enabled

  enabled_cloudwatch_logs_exports = ["postgresql"]

  # apply_immediately is deliberately NOT set: parameter and instance changes wait
  # for the maintenance window rather than restarting the database mid-use.

  # So the managed, retention-bounded group exists before RDS would auto-create an
  # unmanaged never-expire one. See aws_cloudwatch_log_group.rds_postgresql.
  depends_on = [aws_cloudwatch_log_group.rds_postgresql]

  tags = merge(var.tags, { Name = var.name_prefix })
}

# --------------------------------------------------------------------------- #
# ElastiCache Redis
# --------------------------------------------------------------------------- #

resource "aws_elasticache_subnet_group" "this" {
  name       = var.name_prefix
  subnet_ids = var.private_subnet_ids

  tags = merge(var.tags, { Name = var.name_prefix })
}

# Same hazard as the RDS parameter group above — a static name plus
# create_before_destroy makes replacement impossible — but the fix has to differ:
# aws_elasticache_parameter_group does NOT support name_prefix, only name.
#
# So the FAMILY goes in the name. Family is the thing that forces replacement, so
# deriving the name from it guarantees the new group's name differs from the old
# one's and create_before_destroy has room to work. Dots are replaced because
# ElastiCache family strings can carry them ("redis6.x") and parameter-group names
# cannot.
#
# ⚠️ MIGRATION. This is a RENAME on an existing environment (<name_prefix> ->
# <name_prefix>-<family>), so the next apply replaces the group and re-associates the
# replication group. No data loss, but do it in a maintenance window: with
# apply_immediately = false the association update is deferred, and a deferred
# association plus a same-apply delete of the old group can surface
# InvalidCacheParameterGroupState. See infra/README.md.
resource "aws_elasticache_parameter_group" "this" {
  name        = "${var.name_prefix}-${replace(var.redis_family, ".", "")}"
  family      = var.redis_family
  description = "${var.name_prefix} - cache parameters."

  lifecycle {
    create_before_destroy = true
  }
}

# A replication group rather than a bare cache cluster: transit and at-rest
# encryption are only available on a replication group, and a single-node group
# costs the same as a single-node cluster.
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = var.name_prefix
  description          = "${var.name_prefix} - cache and Celery broker."

  engine         = "redis"
  engine_version = var.redis_version
  node_type      = var.redis_node_type

  num_cache_clusters = 1
  port               = 6379

  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [var.redis_security_group_id]
  parameter_group_name = aws_elasticache_parameter_group.this.name

  at_rest_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn

  # ⚠️ Transit encryption changes the CLIENT contract: REDIS_URL must use the
  # rediss:// scheme. See the module README — the two Redis libraries this
  # application uses disagree on the default certificate policy for rediss://,
  # so the URL must also carry ?ssl_cert_reqs=required.
  transit_encryption_enabled = true

  # auth_token is deliberately absent even when redis_auth_enabled is true: the
  # token is a credential and would land in Terraform state. It is set out of band
  # with `aws elasticache modify-replication-group --auth-token ...` and written
  # into the redis-url secret. ignore_changes keeps Terraform from reverting it.
  #
  # ⚠️ That combination is silent by construction — ignore_changes means Terraform
  # can never report a MISSING token either. check "redis_auth_token_applied" below
  # is what makes the gap visible; do not delete it as redundant.
  lifecycle {
    ignore_changes = [auth_token, auth_token_update_strategy]
  }

  apply_immediately = false

  tags = merge(var.tags, { Name = var.name_prefix })
}

# Does the cache ACTUALLY require a token?
#
# redis_auth_enabled used to be consumed by nothing but an output — it created the
# redis-url secret container and set redis_requires_auth_token, and that was all.
# Combined with ignore_changes on auth_token above, an operator who skipped the
# out-of-band `modify-replication-group --auth-token` step left the cache — holding
# Celery task payloads for an environment documented as carrying real borrower NPI —
# accepting unauthenticated connections indefinitely, with every artifact claiming
# otherwise and no drift signal anywhere.
#
# A `check`, not a postcondition, and that choice is deliberate: the token can only
# be applied AFTER the replication group exists, so a hard precondition would
# deadlock the first apply. A check reports on every plan and apply until the token
# is actually in place, then goes quiet — a standing signal rather than a one-shot.
check "redis_auth_token_applied" {
  data "aws_elasticache_replication_group" "current" {
    replication_group_id = aws_elasticache_replication_group.this.id
  }

  assert {
    condition     = !var.redis_auth_enabled || data.aws_elasticache_replication_group.current.auth_token_enabled
    error_message = "redis_auth_enabled is true but ${aws_elasticache_replication_group.this.id} has NO auth token: the cache is accepting unauthenticated connections. Apply it with `aws elasticache modify-replication-group --replication-group-id ${aws_elasticache_replication_group.this.id} --auth-token '<token>' --auth-token-update-strategy SET --apply-immediately`, then put the same token in the redis-url secret."
  }
}

# --------------------------------------------------------------------------- #
# CloudWatch log groups
# --------------------------------------------------------------------------- #

resource "aws_cloudwatch_log_group" "this" {
  for_each = toset(var.log_group_names)

  name              = each.value
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = merge(var.tags, { Name = each.value })
}

# The group RDS would otherwise auto-create for enabled_cloudwatch_logs_exports.
#
# Declared here for exactly the reason log_group_names' own description gives: an
# auto-created group NEVER EXPIRES. Left implicit it also sits outside Terraform
# state, so log_retention_days did not reach it and `terraform destroy` left it
# behind — the retention policy this module advertises as uniform had a hole in it.
#
# ⚠️ MIGRATION. On an environment already applied with enabled_cloudwatch_logs_exports,
# RDS has ALREADY created this group, and Terraform does not adopt existing
# resources — the apply fails with ResourceAlreadyExistsException. Import it first:
#
#   terraform import 'module.data.aws_cloudwatch_log_group.rds_postgresql' \
#     /aws/rds/instance/<name_prefix>/postgresql
#
# A greenfield apply needs nothing.
#
# The name is fixed by RDS: /aws/rds/instance/<db identifier>/<log type>, and the
# identifier is var.name_prefix (see aws_db_instance.this above). The instance
# depends on this group so Terraform creates it FIRST and RDS finds it already
# present, rather than racing to create it unmanaged.
resource "aws_cloudwatch_log_group" "rds_postgresql" {
  name              = "/aws/rds/instance/${var.name_prefix}/postgresql"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = merge(var.tags, { Name = "${var.name_prefix}-rds-postgresql" })
}
