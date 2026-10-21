# Alarms (LP-987). A message in a dead-letter queue is one the worker gave up on; without an alarm the
# only trace is a queue nobody looks at.

resource "aws_cloudwatch_metric_alarm" "inbound_dlq_not_empty" {
  count = var.alarms_enabled ? 1 : 0

  alarm_name        = "${var.name_prefix}-inbound-mail-dlq-not-empty"
  alarm_description = "A received email could not be processed and is in the inbound dead-letter queue. Look at it, fix the cause, then redrive or delete it."

  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [var.alarm_topic_arn]
  ok_actions    = [var.alarm_topic_arn]
  tags          = var.tags
}

# Also gated on the scan: its DLQ exists only when the scan does.
resource "aws_cloudwatch_metric_alarm" "scan_results_dlq_not_empty" {
  count = var.alarms_enabled && var.malware_scan_enabled ? 1 : 0

  alarm_name        = "${var.name_prefix}-scan-results-dlq-not-empty"
  alarm_description = "A malware-scan result could not be processed and is in the scan-results dead-letter queue. Look at it, fix the cause, then redrive or delete it."

  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.scan_results_dlq[0].name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [var.alarm_topic_arn]
  ok_actions    = [var.alarm_topic_arn]
  tags          = var.tags
}
