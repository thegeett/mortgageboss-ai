output "schedule_names" {
  description = "Every schedule this module creates, for `aws scheduler get-schedule`."
  value = concat(
    [for k, s in aws_scheduler_schedule.stop_service : s.name],
    [aws_scheduler_schedule.stop_database.name],
    [for s in aws_scheduler_schedule.stop_database_retry : s.name],
    [aws_scheduler_schedule.start_database.name],
    [for k, s in aws_scheduler_schedule.start_service : s.name],
  )
}

output "schedule_summary" {
  description = <<-EOT
    What fires when, in the configured timezone. Read this rather than reassembling
    the cron expressions by hand — the times the database calls run at are derived,
    not written down anywhere in tfvars.
  EOT
  value = {
    timezone            = var.timezone
    stop_services       = local.cron_stop_services
    stop_database       = local.cron_stop_database
    stop_database_retry = var.stop_retry_after_minutes > 0 ? local.cron_stop_db_retry : "disabled"
    start_database      = local.cron_start_database
    start_services      = local.cron_start_services
    enabled             = var.enabled
  }
}

output "execution_role_arn" {
  description = "The role the schedules assume to call ECS and RDS."
  value       = aws_iam_role.scheduler.arn
}

output "dead_letter_queue_url" {
  description = <<-EOT
    Where a failed invocation reports itself.

    A schedule that fails is otherwise silent — no console banner, no log group —
    so this is the only place a broken schedule shows up before the bill does:

      aws sqs receive-message --queue-url <this> --message-attribute-names All
  EOT
  value       = aws_sqs_queue.dlq.url
}

output "dead_letter_queue_arn" {
  description = "ARN of the dead-letter queue."
  value       = aws_sqs_queue.dlq.arn
}
