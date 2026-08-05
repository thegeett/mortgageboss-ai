output "repository_urls" {
  description = "Map of repository name to its registry URL, for docker push and ECS image references."
  value       = { for k, v in aws_ecr_repository.this : k => v.repository_url }
}

output "repository_arns" {
  description = "Map of repository name to ARN, for the ECS execution role's pull policy."
  value       = { for k, v in aws_ecr_repository.this : k => v.arn }
}
