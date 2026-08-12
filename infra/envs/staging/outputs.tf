# Outputs C3 (ECS services) consumes.
#
# Everything here is an identifier, hostname, or ARN — never key material. No
# secret VALUE is an output anywhere in this configuration, and the RDS master
# password is deliberately not surfaced even though it exists in state.

output "vpc_id" {
  description = "VPC id."
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet ids — the load balancer goes here."
  value       = module.network.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Private subnet ids — ECS tasks, database, cache."
  value       = module.network.private_subnet_ids
}

output "alb_security_group_id" {
  description = "Security group for the load balancer."
  value       = module.network.alb_security_group_id
}

output "ecs_tasks_security_group_id" {
  description = "Security group for ECS tasks."
  value       = module.network.ecs_tasks_security_group_id
}

output "rds_security_group_id" {
  description = "Security group for the database."
  value       = module.network.rds_security_group_id
}

output "redis_security_group_id" {
  description = "Security group for the cache."
  value       = module.network.redis_security_group_id
}

# ecr_repository_urls is deliberately NOT an output here — the registry moved to
# ../../shared so that destroying this environment cannot delete another
# environment's images. Get the URLs with:
#   terraform -chdir=../../shared output ecr_repository_urls

output "rds_endpoint" {
  description = "Database endpoint, host:port. A hostname, not a credential."
  value       = module.data.db_endpoint
}

output "rds_address" {
  description = "Database hostname."
  value       = module.data.db_address
}

output "rds_database_name" {
  description = "Initial database name."
  value       = module.data.db_name
}

output "rds_username" {
  description = "Master username. The password is never output."
  value       = module.data.db_username
}

output "redis_primary_endpoint" {
  description = "Cache primary endpoint hostname."
  value       = module.data.redis_primary_endpoint
}

output "redis_url_scheme" {
  description = "Scheme REDIS_URL must use, WITHOUT the \"://\" separator - the bare string `rediss`. A consumer must add the separator itself."
  value       = module.data.redis_url_scheme
}

output "redis_requires_auth_token" {
  description = "Whether an AUTH token must be applied out of band, making REDIS_URL a secret."
  value       = module.data.redis_requires_auth_token
}

output "kms_key_arn" {
  description = "Customer-managed key ARN — for the ECS execution role's decrypt permission."
  value       = module.secrets.kms_key_arn
}

output "kms_alias" {
  description = "Alias for the customer-managed key."
  value       = module.secrets.kms_alias
}

output "secret_arns" {
  description = "Map of short secret name to ARN, for the task definition's secrets[] block. ARNs only."
  value       = module.secrets.secret_arns
}

output "secret_names" {
  description = "Map of short secret name to full Secrets Manager path — used by the populate commands."
  value       = module.secrets.secret_names
}

output "log_group_names" {
  description = "CloudWatch log groups created with retention already set."
  value       = module.data.log_group_names
}

output "documents_bucket_arn" {
  description = "ARN of the documents bucket — scopes the ECS task roles' S3 policy."
  value       = module.documents.bucket_arn
}

# --- Compute (C3) ----------------------------------------------------------- #

output "alb_dns_name" {
  description = "Public DNS name of the load balancer — the application is reachable here over HTTP until C4 adds TLS."
  value       = module.compute.alb_dns_name
}

output "alb_zone_id" {
  description = "Load balancer hosted zone id — C4 needs it for the alias record."
  value       = module.compute.alb_zone_id
}

output "http_listener_arn" {
  description = "HTTP listener ARN — C4 attaches HTTPS alongside it."
  value       = module.compute.http_listener_arn
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = module.compute.cluster_name
}

output "ecs_service_names" {
  description = "Map of service key to ECS service name."
  value       = module.compute.service_names
}

output "ecs_task_definition_arns" {
  description = "Map of task key to task definition ARN, including the run-once migration task."
  value       = module.compute.task_definition_arns
}

output "ecs_task_role_arns" {
  description = "Map of task key to task role ARN. Identifiers, not credentials."
  value       = module.compute.task_role_arns
}

output "ecs_execution_role_arn" {
  description = "Shared ECS execution role ARN."
  value       = module.compute.execution_role_arn
}

output "migration_run_task_command" {
  description = "Ready-to-paste `aws ecs run-task` invocation for the Alembic migration."
  value       = module.compute.migration_run_task_command
}

output "execute_command_invocations" {
  description = "Map of service key to its `aws ecs execute-command` invocation."
  value       = module.compute.execute_command_invocations
}

output "container_image_uris" {
  description = "The exact image URIs the task definitions reference — check these match what was pushed."
  value = {
    api      = "${local.ecr_repository_urls["api"]}:${var.image_tag}"
    frontend = "${local.ecr_repository_urls["frontend"]}:${var.image_tag}"
  }
}

# --- DNS / TLS (C4) ---------------------------------------------------------- #

output "route53_name_servers" {
  description = <<-EOT
    ⚠️ THE FOUR NAMESERVERS TO ENTER AT THE REGISTRAR.

    The output of phase 1 and the input to the manual delegation step. Read with:
      terraform output -json route53_name_servers
    Verify delegation is live before phase 2 with:
      dig +short NS <domain>
  EOT
  value       = module.dns.name_servers
}

output "route53_zone_id" {
  description = "Hosted zone id for the delegated subdomain."
  value       = module.dns.zone_id
}

output "certificate_arn" {
  description = "ACM certificate ARN — null until phase 2."
  value       = module.dns.certificate_arn
}

output "application_url" {
  description = "Where the application is reachable once phase 2 is applied."
  value       = var.enable_tls ? "https://${var.domain_name}" : "http://${module.compute.alb_dns_name} (pre-TLS)"
}

output "cognito_user_pool_id" {
  description = "User pool id — needed for the admin-create-user command. An identifier, not a credential."
  value       = module.compute.cognito_user_pool_id
}

output "documents_bucket" {
  description = "Documents bucket name — the application's S3_BUCKET setting."
  value       = module.documents.bucket_name
}
