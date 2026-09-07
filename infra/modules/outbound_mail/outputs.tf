output "send_domain" {
  description = "The From: domain. Becomes the outbound identity every template signs off as."
  value       = var.send_domain
}

output "bounce_domain" {
  description = "The envelope sender / Return-Path domain."
  value       = var.bounce_domain
}

output "configuration_set_name" {
  description = "Named on every send so delivery events are published. LP-811/LP-816 pass this."
  value       = aws_ses_configuration_set.this.name
}

output "events_topic_arn" {
  description = "SNS topic carrying bounce, complaint, reject and delivery events. LP-819 reads it."
  value       = aws_sns_topic.events.arn
}

output "dkim_tokens" {
  description = "The three Easy DKIM tokens, for checking the published CNAMEs by hand."
  value       = aws_ses_domain_dkim.send.dkim_tokens
}
