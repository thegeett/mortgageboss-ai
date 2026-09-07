output "bucket_name" {
  description = "Bucket holding raw inbound .eml objects."
  value       = aws_s3_bucket.this.id
}

output "bucket_arn" {
  value = aws_s3_bucket.this.arn
}

output "object_prefix" {
  description = "Key prefix every stored message lands under."
  value       = local.object_prefix
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

output "receipt_rule_name" {
  description = "Named in the SES source-ARN conditions on the bucket, topic and key policies."
  value       = aws_ses_receipt_rule.store.name
}

output "mail_domain" {
  description = "Becomes settings.inbox_domain (LP-802)."
  value       = var.mail_domain
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
