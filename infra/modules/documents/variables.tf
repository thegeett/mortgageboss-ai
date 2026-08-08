variable "bucket_name" {
  description = "Globally-unique bucket name."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "kms_key_arn" {
  description = <<-EOT
    CMK used for SSE-KMS default encryption.

    The same ARN must be passed to the compute module as
    documents_bucket_kms_key_arn, or the task roles get no KMS statements and every
    upload fails with an opaque AccessDenied from S3 rather than from KMS.
  EOT
  type        = string
}
