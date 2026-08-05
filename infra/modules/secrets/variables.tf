variable "name_prefix" {
  description = "Prefix for resource names and the KMS alias."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "secret_path_prefix" {
  description = <<-EOT
    Path prefix for Secrets Manager secret names, e.g. "mbai/<environment>".
    Secrets are created as <prefix>/database-url and so on.

    Separate from name_prefix because Secrets Manager uses a slash-delimited path
    convention while every other resource uses a dash-delimited name.
  EOT
  type        = string
}

variable "recovery_window_days" {
  description = <<-EOT
    Days a deleted secret stays recoverable before the name is released.

    0 = delete immediately. Correct for a throwaway environment that is destroyed
    and rebuilt: a non-zero window leaves the NAME RESERVED, so destroy-then-apply
    fails with a name conflict.

    STAGING AND PRODUCTION MUST USE 30. Zero there means a fat-fingered destroy is
    unrecoverable.
  EOT
  type        = number

  validation {
    condition     = var.recovery_window_days == 0 || (var.recovery_window_days >= 7 && var.recovery_window_days <= 30)
    error_message = "recovery_window_days must be 0 (immediate) or between 7 and 30 — AWS rejects everything else."
  }
}

variable "create_redis_url_secret" {
  description = <<-EOT
    Create a secret container for REDIS_URL.

    Required when the cache uses an AUTH token, because the token is embedded in
    the URL and that makes the whole URL a credential. With transit encryption but
    no AUTH token the URL is topology only — CONFIG, not a secret.

    Must agree with the data module's auth-token setting; envs/*/main.tf wires
    both from one variable so they cannot drift apart.
  EOT
  type        = bool
}

variable "kms_create_alias" {
  description = <<-EOT
    Create a friendly alias for the KMS key.

    The alias is CONSOLE READABILITY ONLY — every consumer references the key by
    ARN through this module's outputs, so nothing functional depends on it.

    ⚠️ It is also the one thing that breaks destroy-and-rebuild. `terraform destroy`
    schedules the key for deletion but leaves the ALIAS ORPHANED
    (hashicorp/terraform-provider-aws#35161), so the next apply fails with
    AlreadyExistsException and needs a manual `aws kms delete-alias`.

    So: FALSE for a throwaway environment that is rebuilt often, TRUE for a
    long-lived one where the console readability is worth more than the rebuild
    friction that will rarely be exercised.
  EOT
  type        = bool
}

variable "kms_deletion_window_days" {
  description = "Waiting period before a scheduled KMS key deletion completes. AWS permits 7-30."
  type        = number

  validation {
    condition     = var.kms_deletion_window_days >= 7 && var.kms_deletion_window_days <= 30
    error_message = "kms_deletion_window_days must be between 7 and 30."
  }
}
