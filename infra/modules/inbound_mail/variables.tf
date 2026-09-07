variable "name_prefix" {
  description = "Dash-delimited resource name prefix, e.g. mbai-staging."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}

variable "mail_domain" {
  description = <<-EOT
    The domain that RECEIVES borrower mail, e.g. inbox.staging.mortgageboss.ai.

    It must be a domain that sends nothing. An inbound MX overlapping an authenticated
    SENDING domain is the documented cause of an infinite mail loop, so this is deliberately
    a subdomain of its own with no SPF, no DKIM and no A record — see the module header.
  EOT
  type        = string
}

variable "route53_zone_id" {
  description = "The hosted zone the MX and verification records are written into."
  type        = string
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
  description = "Bucket that receives raw .eml objects."
  type        = string
}

variable "kms_key_arn" {
  description = "Customer managed key for SSE-KMS on the bucket and on the SES write."
  type        = string
}

variable "retention_years" {
  description = <<-EOT
    How long a raw inbound message is kept. The execution protocol fixes this at 5 years,
    matching the Closing Disclosure floor.

    Retention pulls two ways: 5 years is a FLOOR for some records, and the Safeguards Rule
    imposes a 2-year disposal duty from last use for others. Keeping everything forever is a
    finding, not just a cost — which is why this is a variable with a stated default rather
    than an omitted lifecycle rule.
  EOT
  type        = number
  default     = 5
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
