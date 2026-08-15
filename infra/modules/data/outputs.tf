output "db_endpoint" {
  description = "Database endpoint, host:port. A hostname, not a credential."
  value       = aws_db_instance.this.endpoint
}

output "db_address" {
  description = "Database hostname only."
  value       = aws_db_instance.this.address
}

output "db_port" {
  description = "Database port."
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "Initial database name."
  value       = aws_db_instance.this.db_name
}

output "db_username" {
  description = "Master username. Not a credential on its own; the password is never output."
  value       = aws_db_instance.this.username
}

output "redis_primary_endpoint" {
  description = "Cache primary endpoint hostname."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "redis_port" {
  description = "Cache port."
  value       = aws_elasticache_replication_group.this.port
}

output "redis_url_scheme" {
  description = <<-EOT
    The scheme REDIS_URL must use, WITHOUT the "://" separator — the value is the
    bare string `rediss`, and a consumer must add the separator itself.

    ⚠️ This description previously read "Always rediss://" while the value was
    bare, and a consumer built its URL by concatenation on the strength of it:
    `rediss:<TOKEN>@host` on one path and `redissmaster.example.com` on the
    other. Both were rejected downstream, so it failed safe — but the wording is
    what caused it. The scheme is always `rediss` because transit encryption is
    enabled unconditionally and a redis:// client cannot connect to a
    TLS-required cache.
  EOT
  value       = "rediss"
}

output "redis_requires_auth_token" {
  description = <<-EOT
    Whether an AUTH token must be applied out of band. When true, REDIS_URL
    carries the token and is therefore a SECRET rather than CONFIG.

    ⚠️ This is the REQUESTED state, not the observed one — it is just
    var.redis_auth_enabled echoed back. Whether the token is actually on the cache
    is reported by check "redis_auth_token_applied" (see main.tf), which fires on
    every plan until it is.
  EOT
  value       = var.redis_auth_enabled
}

output "log_group_names" {
  description = "Created CloudWatch log group names."
  value       = [for g in aws_cloudwatch_log_group.this : g.name]
}

output "log_group_arns" {
  description = <<-EOT
    Created CloudWatch log group ARNs.

    Needed so the ECS execution role's logs:PutLogEvents can be scoped to exactly
    these groups rather than "*" — a role that may write to any log group in the
    account is a role that may also create noise anywhere in it.
  EOT
  value       = [for g in aws_cloudwatch_log_group.this : g.arn]
}

output "log_group_arns_by_key" {
  description = "Map of the trailing path segment (api/worker/frontend) to log group ARN."
  value       = { for k, g in aws_cloudwatch_log_group.this : reverse(split("/", k))[0] => g.arn }
}

output "log_group_names_by_key" {
  description = "Map of the trailing path segment (api/worker/frontend) to log group NAME, for the awslogs driver."
  value       = { for k, g in aws_cloudwatch_log_group.this : reverse(split("/", k))[0] => g.name }
}

# The master password is deliberately NOT an output. It exists in state (a
# random_password always does) but nothing surfaces it, so it cannot leak through
# `terraform output`, a CI log, or a downstream module. The operator assembles
# DATABASE_URL by hand — see infra/README.md.

# The DBI RESOURCE ID (db-XXXXXXXX...), not the instance identifier. This is the only
# form `rds-db:connect` accepts in a resource ARN, and the two look similar enough that
# using the wrong one produces a "PAM authentication failed" that says nothing about IAM.
# C7's read-only query role authenticates with an IAM token against this id.
output "db_instance_resource_id" {
  description = "RDS DBI resource id, for rds-db:connect resource ARNs."
  value       = aws_db_instance.this.resource_id
}
