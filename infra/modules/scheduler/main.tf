# Scheduler — takes the environment offline overnight and brings it back.
#
# Eight EventBridge Scheduler schedules that scale the three ECS services to zero
# and stop the RDS instance at night, then reverse it on a weekday morning. No
# Lambda, no application code: Scheduler's UNIVERSAL TARGETS call the AWS SDK
# directly, so the target is an ARN plus a JSON request body.
#
# Free at this volume — 14M invocations a month are included and this uses ~250.
#
# EventBridge Scheduler rather than a classic EventBridge rule, for two reasons:
# a rule cannot call the SDK without a Lambda in between, and a rule is UTC-only.
# Scheduler takes an IANA `schedule_expression_timezone`, so the crons below are
# written in local time and DST is handled without a second set of schedules.
#
# THIS MODULE DEPENDS ON `ignore_changes = [desired_count]` IN modules/compute.
# Without it, the next `terraform apply` after a 22:00 scale-down puts all three
# services back to their tfvars count and the environment runs all night. See
# docs/tickets/LP-630.md, Phase A.
#
# WHAT THIS MODULE DELIBERATELY DOES NOT DO
#
# It is not the equivalent of `./scripts/deploy <env> down`. That command scales,
# WAITS for the tasks to actually stop, CHECKS that no one-off task is running,
# and only then stops the database. A universal target is one API call: it cannot
# wait, cannot check, and cannot refuse. The 15 minutes between the ECS and RDS
# schedules stands in for the drain wait (an idle worker drains in ~10s, a busy
# one within its 120s stop timeout), but nothing here notices a `migrate`,
# `backfill-mismo` or `verify` task still running at 22:00 — that task loses its
# database connection. Accepted deliberately: the blast radius is one interrupted
# staging job overnight, and closing it properly needs a Lambda or a container
# running the deploy script. `down` stays the safe path when a human is driving.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  # One schedule per service: an EventBridge Scheduler schedule has exactly ONE
  # target, which is why four rows in the ticket's table are eight schedules.
  services = var.service_names

  # All times are minutes-since-midnight in var.timezone, so the derived ones are
  # simple addition. Doing this as `hour + 1` in the resource would produce
  # `cron(0 24 ...)` for a 23:00 stop -- accepted by Terraform, rejected by AWS.
  stop_at       = var.stop_hour * 60 + var.stop_minute
  stop_db_at    = local.stop_at + var.stop_grace_minutes
  stop_db_retry = local.stop_db_at + var.stop_retry_after_minutes
  start_at      = var.start_hour * 60 + var.start_minute
  start_db_at   = local.start_at - var.start_lead_minutes

  # `cron(minute hour ? * DAYS *)`, written in var.timezone rather than UTC.
  cron_stop_services  = format("cron(%d %d ? * %s *)", local.stop_at % 60, floor(local.stop_at / 60), var.stop_days)
  cron_stop_database  = format("cron(%d %d ? * %s *)", local.stop_db_at % 60, floor(local.stop_db_at / 60), var.stop_days)
  cron_stop_db_retry  = format("cron(%d %d ? * %s *)", local.stop_db_retry % 60, floor(local.stop_db_retry / 60), var.stop_days)
  cron_start_database = format("cron(%d %d ? * %s *)", local.start_db_at % 60, floor(local.start_db_at / 60), var.start_days)
  cron_start_services = format("cron(%d %d ? * %s *)", local.start_at % 60, floor(local.start_at / 60), var.start_days)
}

# Every derived time has to stay inside its own day. A stop at 23:50 with a
# 15-minute grace, or a 00:05 start with a 15-minute lead, would silently wrap and
# schedule the database call for the wrong day -- or emit an hour AWS rejects.
# Caught at plan time rather than at 22:00.
resource "terraform_data" "time_bounds" {
  input = local.stop_at

  lifecycle {
    precondition {
      condition     = local.stop_db_retry < 1440
      error_message = "stop time + stop_grace_minutes + stop_retry_after_minutes must stay within the same day (got ${local.stop_db_retry} minutes past midnight, max 1439). Move the stop earlier or shorten the grace."
    }

    precondition {
      condition     = local.start_db_at >= 0
      error_message = "start time - start_lead_minutes must not cross midnight (got ${local.start_db_at}). Move the start later or shorten the lead."
    }

    precondition {
      condition     = local.start_at < local.stop_at
      error_message = "The start (${local.start_at} min) must come before the stop (${local.stop_at} min) on the clock -- the environment is meant to be up between them, not down."
    }
  }
}

# --------------------------------------------------------------------------- #
# Execution role
#
# Scoped to this environment's cluster and instance. `iam:PassRole` is not needed:
# a universal target calls the API as this role directly.
# --------------------------------------------------------------------------- #

data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    # Without this a confused-deputy path exists: any other account's schedule
    # could assume the role if it learned the ARN.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  description        = "EventBridge Scheduler role for the overnight shutdown (LP-630)."
  assume_role_policy = data.aws_iam_policy_document.assume.json

  tags = merge(var.tags, { Name = "${var.name_prefix}-scheduler" })
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid    = "ScaleTheServices"
    effect = "Allow"
    # UpdateService alone. Not RegisterTaskDefinition, not DeleteService: this role
    # exists to move a number between 0 and N.
    actions   = ["ecs:UpdateService"]
    resources = var.service_arns
  }

  statement {
    sid    = "StartAndStopTheInstance"
    effect = "Allow"
    actions = [
      "rds:StopDBInstance",
      "rds:StartDBInstance",
      "rds:DescribeDBInstances",
    ]
    resources = [var.db_instance_arn]
  }

  statement {
    sid       = "ReportItsOwnFailures"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "${var.name_prefix}-scheduler"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

# --------------------------------------------------------------------------- #
# Dead-letter queue
#
# The reason this exists: a schedule that fails is SILENT. There is no console
# banner and no log group; the invocation simply does not happen, and the first
# anyone knows is a bill that did not fall or an environment that did not come
# back. A DLQ turns every target error into a message carrying the API's own
# error code and text.
#
# Read it with:
#   aws sqs receive-message --queue-url <url> --message-attribute-names All
# --------------------------------------------------------------------------- #

resource "aws_sqs_queue" "dlq" {
  name = "${var.name_prefix}-scheduler-dlq"

  # 14 days: long enough that a failure over a holiday weekend is still there on
  # the Monday.
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-scheduler-dlq" })
}

# --------------------------------------------------------------------------- #
# Schedules — down
#
# The stop runs EVERY day, including at weekends, while the start runs on
# weekdays only. That asymmetry is deliberate: Friday 22:00 to Monday 09:00 is
# one continuous shutdown, and the Saturday and Sunday stops fire against an
# already-stopped instance as harmless no-ops. They are what reaps AWS's
# seven-day force-start, which would otherwise leave the environment running
# from the moment it fired until someone noticed.
# --------------------------------------------------------------------------- #

resource "aws_scheduler_schedule" "stop_service" {
  for_each = local.services

  name        = "${var.name_prefix}-stop-${each.key}"
  description = "LP-630: scale ${each.key} to 0 at ${var.stop_hour}:${format("%02d", var.stop_minute)} ${var.timezone}."
  group_name  = "default"
  state       = var.enabled ? "ENABLED" : "DISABLED"

  # OFF, not a window. A flexible window would let AWS fire this up to N minutes
  # late, which would eat into the gap before the database stops.
  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = local.cron_stop_services
  schedule_expression_timezone = var.timezone

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ecs:updateService"
    role_arn = aws_iam_role.scheduler.arn

    input = jsonencode({
      Cluster      = var.cluster_name
      Service      = each.value
      DesiredCount = 0
    })

    retry_policy {
      maximum_retry_attempts       = 3
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }
}

resource "aws_scheduler_schedule" "stop_database" {
  name        = "${var.name_prefix}-stop-database"
  description = "LP-630: stop the RDS instance, ${var.stop_grace_minutes} minutes after the services are told to scale to 0."
  group_name  = "default"
  state       = var.enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = local.cron_stop_database
  schedule_expression_timezone = var.timezone

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:rds:stopDBInstance"
    role_arn = aws_iam_role.scheduler.arn

    # `DbInstanceIdentifier`, NOT `DBInstanceIdentifier`.
    #
    # The RDS API reference spells it `DBInstanceIdentifier`, and that spelling
    # is REJECTED here. A universal target serialises through the AWS SDK, whose
    # naming strategy lowercases the acronym, and Scheduler expects the SDK
    # member name. The failure mode is the worst kind: the schedule is created
    # happily, `terraform plan` is clean, and the invocation fails at 22:00 every
    # night with a validation error nobody sees. The DLQ above exists so that
    # this class of mistake reports itself. Verify after the first apply --
    # see the module README.
    input = jsonencode({
      DbInstanceIdentifier = var.db_instance_identifier
    })

    # More generous than the ECS retries. If the instance is momentarily in a
    # state that refuses a stop, retrying over the next two hours is exactly
    # right -- the environment is idle, and every retry that succeeds is a night
    # that does not get billed.
    retry_policy {
      maximum_retry_attempts       = 10
      maximum_event_age_in_seconds = 7200
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }
}

# A second attempt, an hour later, every day.
#
# Not belt-and-braces for its own sake. The 22:15 stop can legitimately fail: an
# instance that is `backing-up` or `modifying` refuses a stop, and RDS takes an
# automated snapshot on a schedule this module does not control. The retry policy
# above covers minutes; this covers the case where the instance was busy for the
# whole window. Stopping an already-stopped instance is an error, which is why it
# has a DLQ too -- expect this one to appear there on most nights, harmlessly.
resource "aws_scheduler_schedule" "stop_database_retry" {
  count = var.stop_retry_after_minutes > 0 ? 1 : 0

  name        = "${var.name_prefix}-stop-database-retry"
  description = "LP-630: second stop attempt, for a night when the instance was busy at the first."
  group_name  = "default"
  state       = var.enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = local.cron_stop_db_retry
  schedule_expression_timezone = var.timezone

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:rds:stopDBInstance"
    role_arn = aws_iam_role.scheduler.arn

    input = jsonencode({
      DbInstanceIdentifier = var.db_instance_identifier
    })

    retry_policy {
      maximum_retry_attempts       = 3
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }
}

# --------------------------------------------------------------------------- #
# Probe — a one-off schedule, for proving the wiring without waiting for 22:00.
#
# The universal-target input keys are the one thing here that fails SILENTLY and
# cannot be checked by `terraform plan`: the API reference spells the RDS
# parameter `DBInstanceIdentifier`, the SDK spells it `DbInstanceIdentifier`, and
# a wrong key produces a schedule that is created happily and then does nothing,
# every night, with no signal anywhere.
#
# Set `probe_at` to a UTC timestamp a few minutes ahead, apply, wait, then read
# the dead-letter queue. It targets startDBInstance against an instance that is
# already running, so it cannot change anything either way — the two outcomes are
# distinguishable purely by which error comes back:
#
#   "InvalidDBInstanceState"  the key was accepted and RDS was really called.
#                             The wiring works. This is the PASS.
#   a validation/parse error  the key was rejected before RDS was reached.
#                             The spelling is wrong.
#
# Unset it again afterwards. Left set, it is one dead schedule that never fires
# twice, but it is noise in the plan.
# --------------------------------------------------------------------------- #

resource "aws_scheduler_schedule" "probe" {
  count = var.probe_at == null ? 0 : 1

  name        = "${var.name_prefix}-scheduler-probe"
  description = "LP-630: one-off, proves the universal-target input shape reaches RDS. Safe: starts an already-running instance."
  group_name  = "default"
  state       = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "at(${var.probe_at})"
  schedule_expression_timezone = "UTC"

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:rds:startDBInstance"
    role_arn = aws_iam_role.scheduler.arn

    input = jsonencode({
      DbInstanceIdentifier = var.db_instance_identifier
    })

    # No retries: one attempt, one message in the queue, one unambiguous answer.
    retry_policy {
      maximum_retry_attempts = 0
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }
}

# --------------------------------------------------------------------------- #
# Schedules — up
#
# Database first, by var.start_lead_minutes. A task that starts before Postgres
# answers fails its readiness check, the ALB pulls it out of rotation, and the
# deployment circuit breaker can roll the whole thing back.
#
# Measured on this environment 2026-08-26: a `db.t4g.small` took ~4.5 minutes
# from `start-db-instance` to `available`, including a restart while enhanced
# monitoring and Performance Insights reconfigured. 15 minutes leaves ~10 of
# slack. AWS documents 3-7 minutes as the normal range.
# --------------------------------------------------------------------------- #

resource "aws_scheduler_schedule" "start_database" {
  name        = "${var.name_prefix}-start-database"
  description = "LP-630: start the RDS instance, ${var.start_lead_minutes} minutes before the services scale up."
  group_name  = "default"
  state       = var.enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = local.cron_start_database
  schedule_expression_timezone = var.timezone

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:rds:startDBInstance"
    role_arn = aws_iam_role.scheduler.arn

    input = jsonencode({
      DbInstanceIdentifier = var.db_instance_identifier
    })

    # The important retry of the four. An instance still `stopping` when this
    # fires refuses a start, and if the start never lands the services come up at
    # 09:00 against nothing. Ten attempts over an hour covers a slow stop without
    # needing a person.
    retry_policy {
      maximum_retry_attempts       = 10
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }
}

resource "aws_scheduler_schedule" "start_service" {
  for_each = local.services

  name        = "${var.name_prefix}-start-${each.key}"
  description = "LP-630: scale ${each.key} back to ${var.desired_counts[each.key]}."
  group_name  = "default"
  state       = var.enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = local.cron_start_services
  schedule_expression_timezone = var.timezone

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ecs:updateService"
    role_arn = aws_iam_role.scheduler.arn

    # The count comes from the same tfvars variable Terraform used to CREATE the
    # service. Since Phase A those two can drift -- the tfvar no longer reaches
    # a live service -- so this schedule is what makes the tfvar effective again
    # every morning, exactly as `./scripts/deploy <env> up` does.
    input = jsonencode({
      Cluster      = var.cluster_name
      Service      = each.value
      DesiredCount = var.desired_counts[each.key]
    })

    retry_policy {
      maximum_retry_attempts       = 5
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }
}
