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
resource "aws_db_parameter_group" "this" {
  name        = var.name_prefix
  family      = var.postgres_family
  description = "${var.name_prefix} — forces TLS on every connection."

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

  # RDS rejects '/', '@', '"' and space in a master password. Excluding the wider
  # punctuation set also keeps the value safe to paste into a URL without
  # percent-encoding, which is how it will actually be used.
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
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

resource "aws_elasticache_parameter_group" "this" {
  name        = var.name_prefix
  family      = var.redis_family
  description = "${var.name_prefix} — cache parameters."

  lifecycle {
    create_before_destroy = true
  }
}

# A replication group rather than a bare cache cluster: transit and at-rest
# encryption are only available on a replication group, and a single-node group
# costs the same as a single-node cluster.
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = var.name_prefix
  description          = "${var.name_prefix} — cache and Celery broker."

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
  lifecycle {
    ignore_changes = [auth_token, auth_token_update_strategy]
  }

  apply_immediately = false

  tags = merge(var.tags, { Name = var.name_prefix })
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
