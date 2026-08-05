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

output "ecr_repository_urls" {
  description = "Map of repository name to registry URL — docker push targets and ECS image references."
  value       = module.registry.repository_urls
}

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
  description = "Scheme REDIS_URL must use — always rediss:// (transit encryption is unconditional)."
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

output "documents_bucket" {
  description = "The hand-created documents bucket. Looked up, NOT managed by this Terraform."
  value       = data.aws_s3_bucket.documents.bucket
}

output "documents_bucket_arn" {
  description = "ARN of the documents bucket — for the ECS task role's S3 policy."
  value       = data.aws_s3_bucket.documents.arn
}
