variable "name_prefix" {
  description = "Dash-delimited resource name prefix, e.g. mbai-staging."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}

variable "aws_region" {
  description = "Region for the SES receipt endpoint. Email receiving is not available everywhere."
  type        = string
}

variable "aws_account_id" {
  description = "Account id, used in the SES source-ARN conditions."
  type        = string
}

variable "bucket_name" {
  description = "Bucket for all raw mail: `inbound/` written by SES, `outbound/` by the worker."
  type        = string
}

variable "kms_key_arn" {
  description = "Customer managed key for the bucket's default SSE-KMS, the SNS topic and the queues."
  type        = string
}

variable "glacier_after_days" {
  description = "Days before an object transitions to Glacier Instant Retrieval."
  type        = number
  default     = 90
}

variable "rule_set_name" {
  description = <<-EOT
    The receipt rule set this rule lives in.

    ONLY ONE RULE SET IS ACTIVE per account per region. If anything else in this account ever
    uses SES receipt, it must be a RULE IN THIS SET, never a second set — activating a second
    set silently deactivates the first, and inbound mail stops with no error anywhere.
  EOT
  type        = string
}

variable "message_retention_seconds" {
  description = "SQS retention. 14 days, the maximum, so a stuck consumer loses nothing."
  type        = number
  default     = 1209600
}

variable "max_receive_count" {
  description = "Receives before a message goes to the DLQ."
  type        = number
  default     = 5
}

variable "malware_scan_enabled" {
  description = <<-EOT
    INFRA-2 — whether to enable GuardDuty Malware Protection for S3 over the inbound bucket.

    Its own flag rather than riding on `inbound_mail_enabled`, because it is its own HUMAN_GATED
    apply and its own cost line. Enabling it on a bucket that receives nothing costs nothing and
    proves the wiring; enabling mail without it would put unscanned borrower attachments into the
    extraction pipeline.
  EOT
  type        = bool
  default     = false
}
