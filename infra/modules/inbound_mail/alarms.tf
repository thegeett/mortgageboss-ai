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

# LP-990 — the rule caught a scan result but could not hand it to its queue. LP-989 found exactly this
# failing silently: no DLQ caught it, so no DLQ alarm could fire. Same gating as the DLQ alarm above.
resource "aws_cloudwatch_metric_alarm" "scan_results_rule_failed" {
  count = var.alarms_enabled && var.malware_scan_enabled ? 1 : 0

  alarm_name        = "${var.name_prefix}-scan-results-rule-failed"
  alarm_description = "A malware-scan result could not be delivered to its queue. Check the KMS key policy (EventBridge grant) and the scan-results queue policies."

  namespace           = "AWS/Events"
  metric_name         = "FailedInvocations"
  dimensions          = { RuleName = aws_cloudwatch_event_rule.scan_results[0].name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [var.alarm_topic_arn]
  ok_actions    = [var.alarm_topic_arn]
  tags          = var.tags
}
