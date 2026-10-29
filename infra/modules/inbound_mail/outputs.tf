output "bucket_name" {
  description = "Bucket holding all raw mail, inbound and outbound."
  value       = aws_s3_bucket.this.id
}

output "bucket_arn" {
  value = aws_s3_bucket.this.arn
}

# LP-992 — read from the bucket's own default-encryption rule, so the app's MAIL_KMS_KEY_ID is
# this bucket's key by construction rather than by two inputs happening to match.
output "kms_key_arn" {
  description = "The CMK the bucket's default encryption uses; writers send it as SSEKMSKeyId."
  value       = one(aws_s3_bucket_server_side_encryption_configuration.this.rule).apply_server_side_encryption_by_default[0].kms_master_key_id
}

output "inbound_prefix" {
  description = "Key prefix SES writes received mail under."
  value       = local.object_prefix
}

output "outbound_prefix" {
  description = "Key prefix the worker writes a copy of each sent message under."
  value       = local.outbound_prefix
}

output "queue_url" {
  description = "SQS queue the worker polls. Becomes settings.inbound_queue_url (LP-802)."
  value       = aws_sqs_queue.this.id
}

output "queue_arn" {
  value = aws_sqs_queue.this.arn
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "topic_arn" {
  value = aws_sns_topic.this.arn
}

output "rule_set_name" {
  description = "The rule set to activate by hand, once per account (`set-active-receipt-rule-set`)."
  value       = aws_ses_receipt_rule_set.this.rule_set_name
}

output "receipt_rule_name" {
  description = "Named in the SES source-ARN conditions on the bucket, topic and key policies."
  value       = aws_ses_receipt_rule.store.name
}

output "scan_results_queue_url" {
  description = "SQS queue carrying GuardDuty scan results and plan-health events, or null."
  value       = var.malware_scan_enabled ? aws_sqs_queue.scan_results[0].id : null
}

output "scan_results_queue_arn" {
  value = var.malware_scan_enabled ? aws_sqs_queue.scan_results[0].arn : null
}

output "malware_scan_role_arn" {
  description = "The role GuardDuty assumes to read and tag objects in the inbound bucket."
  value       = var.malware_scan_enabled ? aws_iam_role.malware_scan[0].arn : null
}
