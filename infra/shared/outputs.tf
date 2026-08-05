output "ecr_repository_urls" {
  description = "Map of repository name to registry URL — docker push targets and ECS image references."
  value       = module.registry.repository_urls
}

output "kms_key_arn" {
  description = "ARN of the key encrypting the images — this state's own key, or the adopted one when registry_kms_key_arn is set."
  value       = local.registry_kms_key_arn
}

output "registry_key_is_owned_here" {
  description = <<-EOT
    False when the images are still encrypted with an ENVIRONMENT's CMK (the
    migration path). While false, that environment's `terraform destroy` schedules
    deletion of the key protecting every image — see infra/README.md.
  EOT
  value       = var.registry_kms_key_arn == null
}
