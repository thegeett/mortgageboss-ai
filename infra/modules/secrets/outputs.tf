# ⚠️ The depends_on below is load-bearing. Do not remove it as "redundant because the
# value already references the key".
#
# aws_kms_key_policy is a SIBLING of aws_kms_key, not an ancestor, so without this the
# policy was an unordered peer of every consumer of this output. Terraform was free to
# create the KMS-encrypted CloudWatch log groups before PutKeyPolicy ran — and a fresh
# key created without a `policy` argument carries only the default root policy, with no
# logs.<region>.amazonaws.com grant. The first apply on a clean account therefore died
# intermittently with the opaque InvalidParameterException that main.tf warns about.
# Making the OUTPUT depend on the policy pushes that ordering to every consumer at once
# (data, registry) rather than relying on each root module to remember a depends_on.
#
# Residual risk, stated honestly: KMS policy propagation is eventually consistent, so
# correct ordering makes the failure rare rather than impossible. If it is still seen on
# a cold account, the next step is a short time_sleep after the policy — deliberately not
# added here, since it means taking on the hashicorp/time provider for a retry.
output "kms_key_arn" {
  description = "ARN of the customer-managed key. Not sensitive — an ARN is an identifier, not key material."
  value       = aws_kms_key.this.arn

  # The depends_on is the whole point — do not drop it as redundant.
  depends_on = [aws_kms_key_policy.this]
}

output "kms_key_id" {
  description = "Key id of the customer-managed key."
  value       = aws_kms_key.this.key_id
}

output "kms_alias" {
  description = <<-EOT
    Alias name for the customer-managed key, or null when kms_create_alias is
    false. Consumers must use kms_key_arn — the alias is console readability only
    and is deliberately absent in rebuild-often environments.
  EOT
  value       = var.kms_create_alias ? aws_kms_alias.this[0].name : null
}

output "secret_arns" {
  description = "Map of short secret name to ARN, for the ECS execution role's secrets[] injection. ARNs only — no values."
  value       = { for k, v in aws_secretsmanager_secret.this : k => v.arn }
}

output "secret_names" {
  description = "Map of short secret name to full Secrets Manager path, for the populate commands."
  value       = { for k, v in aws_secretsmanager_secret.this : k => v.name }
}
