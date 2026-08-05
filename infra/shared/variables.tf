variable "aws_region" {
  description = "Region holding the registry. Must match the environments' region — a cross-region pull is billed and slow."
  type        = string
}

variable "aws_account_id" {
  description = "Expected account id. The apply refuses to run anywhere else (see terraform_data.account_guard)."
  type        = string
}

variable "kms_deletion_window_days" {
  description = "Waiting period before a scheduled KMS key deletion completes."
  type        = number
  default     = 30
}

variable "ecr_repository_names" {
  description = <<-EOT
    Full ECR repository names, e.g. ["mbai/api", "mbai/frontend"].

    NOT prefixed per environment: one registry serves every environment, which is
    distinguished by image TAG. That is what allows the exact bytes tested in dev
    to be promoted to staging rather than rebuilt.
  EOT
  type        = list(string)
}

variable "ecr_keep_last_images" {
  description = <<-EOT
    How many ordinary images to retain, counted across ALL environments now that
    the registry is shared. Promoted tags are protected separately — see
    ecr_protected_tag_prefixes — so this only bounds throwaway CI builds.
  EOT
  type        = number
}

variable "ecr_protected_tag_prefixes" {
  description = "Tag prefixes for promoted images, held to a deeper history and excluded from ecr_keep_last_images' global count."
  type        = list(string)
}

variable "ecr_keep_last_protected_images" {
  description = "Rollback depth retained per protected prefix."
  type        = number
}

variable "kms_create_alias" {
  description = <<-EOT
    Create alias/mbai-shared-registry.

    ADR-365: `terraform destroy` ORPHANS a KMS alias, so a later re-apply fails
    with AlreadyExistsException. That is acceptable here in a way it is not for a
    throwaway environment — this state is long-lived and destroying it is not a
    routine operation — but it is a knob rather than an assumption, so a rebuild
    after an accidental destroy is not blocked on console surgery.
  EOT
  type        = bool
  default     = true
}

variable "registry_kms_key_arn" {
  description = <<-EOT
    Use an EXISTING key for image encryption instead of creating one.

    Exists solely for the migration path. ECR has no API to re-encrypt a repository,
    so the provider marks encryption_configuration ForceNew: importing repositories
    that were created under an environment's CMK while this module demands a NEW key
    plans a DESTROY of every repository. Set this to the original key's ARN to adopt
    them in place with no replacement.

    Leave null for a greenfield apply, which is the correct long-term shape — a key
    owned by this state, so no environment's destroy can schedule its deletion.
  EOT
  type        = string
  default     = null
}

variable "activate_environment_cost_allocation_tag" {
  description = <<-EOT
    Activate `Environment` as a cost allocation tag for the account.

    Account-level, which is why it lives here rather than in an environment: the
    environments' budget cost_filters match on user:Environment$<name>, and AWS
    Budgets matches NOTHING until the tag is activated. Without it a filtered budget
    reports $0 forever and never fires — an alarm that looks configured and is not.

    ⚠️ Activation is NOT retroactive: cost records written before it takes effect
    carry no tag, so the first period after enabling is partial.

    Must be applied in the PAYER account. Set false if this account is a member of
    an organization whose payer activates tags centrally.
  EOT
  type        = bool
  default     = true
}

variable "ecr_untagged_expire_days" {
  description = "Days after which an untagged image is expired."
  type        = number
}

variable "ecr_force_delete" {
  description = <<-EOT
    Allow `terraform destroy` to delete a repository that still contains images.

    Should stay FALSE. This registry holds every environment's images, so a forced
    destroy is not a rebuild — it discards all image history for all environments.
  EOT
  type        = bool
  default     = false
}
