# Deliberately NO name_prefix here. ECR repositories are shared across
# environments — one registry serves every environment, distinguished by image
# TAG rather than by repository name. Prefixing them per environment would store
# a duplicate copy of every image for each one.

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "repository_names" {
  description = <<-EOT
    Full ECR repository names to create, e.g. ["mbai/api", "mbai/frontend"].

    Passed in whole rather than derived from name_prefix because ECR repositories
    are shared across environments — one registry serves every environment, which
    is distinguished by image TAG, not by repository. Deriving the name
    from name_prefix would create a second copy of every image per environment.
  EOT
  type        = list(string)
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key used to encrypt images at rest."
  type        = string
}

variable "pull_account_ids" {
  description = <<-EOT
    Account ids allowed to PULL from these repositories.

    Empty (the default) means same-account only. Any environment running in a
    different account from the registry MUST appear here, or its ECS tasks fail at
    launch with an authorization error.

    ⚠️ A repository policy alone is not sufficient when images are KMS-encrypted:
    the pulling account also needs `kms:Decrypt` on the key, which the registry's
    owning state grants separately. A missing KMS grant fails with a message naming
    KMS rather than ECR, which is a confusing way to learn this.
  EOT
  type        = list(string)
  default     = []
}

variable "keep_last_images" {
  description = <<-EOT
    How many images to retain before expiry, counted across EVERY environment
    because the registry is shared. This is the ordinary tier — a busy CI pipeline
    burns through it quickly, so it must not be the only thing protecting an image
    another environment is running. See protected_tag_prefixes.
  EOT
  type        = number
}

variable "protected_tag_prefixes" {
  description = <<-EOT
    Tag prefixes for PROMOTED images, matched by a higher-priority lifecycle rule
    so they never enter keep_last_images' count.

    Without this the shared registry's global count evicts the oldest image, which
    is precisely a long-lived staging or production tag; the environment running it
    then fails to launch replacement tasks with CannotPullContainerError.
  EOT
  type        = list(string)
}

variable "keep_last_protected_images" {
  description = "How many images to retain per protected prefix. Deliberately deeper than keep_last_images — this is the rollback history that matters."
  type        = number
}

variable "untagged_expire_days" {
  description = "Days after which an untagged image is expired."
  type        = number
}

variable "force_delete" {
  description = <<-EOT
    Allow `terraform destroy` to delete a repository that still contains images.

    Without this, destroy FAILS on any repository holding an image — manual
    console deletion is then required, which defeats the destroy-and-rebuild
    workflow. Set false for staging and production, where an accidental destroy
    of the image history should be hard.
  EOT
  type        = bool
}
