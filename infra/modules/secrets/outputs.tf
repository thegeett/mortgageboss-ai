output "kms_key_arn" {
  description = "ARN of the customer-managed key. Not sensitive — an ARN is an identifier, not key material."
  value       = aws_kms_key.this.arn
}

output "kms_key_id" {
  description = "Key id of the customer-managed key."
  value       = aws_kms_key.this.key_id
}

output "kms_alias" {
  description = "Alias name for the customer-managed key."
  value       = aws_kms_alias.this.name
}

output "secret_arns" {
  description = "Map of short secret name to ARN, for the ECS execution role's secrets[] injection. ARNs only — no values."
  value       = { for k, v in aws_secretsmanager_secret.this : k => v.arn }
}

output "secret_names" {
  description = "Map of short secret name to full Secrets Manager path, for the populate commands."
  value       = { for k, v in aws_secretsmanager_secret.this : k => v.name }
}
