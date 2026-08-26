variable "name_prefix" {
  description = "Prefix for every resource name and tag in this module."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "account_id" {
  description = <<-EOT
    The AWS account this environment lives in.

    Used as an `aws:SourceAccount` condition on the execution role's trust policy,
    so a schedule in another account cannot assume it.
  EOT
  type        = string
}

# --------------------------------------------------------------------------- #
# What it acts on
# --------------------------------------------------------------------------- #

variable "cluster_name" {
  description = "ECS cluster holding the services to scale."
  type        = string
}

variable "service_names" {
  description = <<-EOT
    Services to scale, as {key => service name}. One schedule pair per entry.

    The key is a label used in schedule names and in `desired_counts`; the value is
    the real ECS service name.
  EOT
  type        = map(string)
}

variable "service_arns" {
  description = <<-EOT
    ARNs of those services, for the execution role's `ecs:UpdateService` statement.

    Separate from `service_names` because the API takes names and IAM takes ARNs,
    and deriving one from the other in the module would hardcode a partition.
  EOT
  type        = list(string)
}

variable "desired_counts" {
  description = <<-EOT
    Task count to restore each morning, keyed as `service_names`.

    This is the environment's tfvars value. Since LP-630 Phase A put
    `ignore_changes = [desired_count]` on the services, the tfvar no longer reaches
    a running service on apply — the morning schedule is what makes it effective
    again, exactly as `./scripts/deploy <env> up` does.
  EOT
  type        = map(number)
}

variable "db_instance_identifier" {
  description = "RDS instance identifier to stop and start."
  type        = string
}

variable "db_instance_arn" {
  description = "ARN of that instance, to scope the execution role to it alone."
  type        = string
}

# --------------------------------------------------------------------------- #
# When
# --------------------------------------------------------------------------- #

variable "timezone" {
  description = <<-EOT
    IANA timezone the schedules are written in, e.g. "America/New_York".

    Not UTC. EventBridge Scheduler applies the zone itself, including DST, so a
    22:00 stop stays at 22:00 local across the March and November transitions
    without a second set of schedules.

    Choose the zone the people using the environment are in — it decides who finds
    it dark. Never infer it from `aws_region`: that is where the infrastructure
    runs, not where anyone works.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z]+/[A-Za-z_+-]+$", var.timezone))
    error_message = "timezone must be an IANA name like \"America/New_York\", not an abbreviation like \"EST\" or a UTC offset."
  }
}

variable "stop_hour" {
  description = "Hour (0-23, local) at which the services scale to zero."
  type        = number

  validation {
    condition     = var.stop_hour >= 0 && var.stop_hour <= 23 && floor(var.stop_hour) == var.stop_hour
    error_message = "stop_hour must be a whole number from 0 to 23."
  }
}

variable "stop_minute" {
  description = "Minute (0-59) at which the services scale to zero."
  type        = number
  default     = 0

  validation {
    condition     = var.stop_minute >= 0 && var.stop_minute <= 59 && floor(var.stop_minute) == var.stop_minute
    error_message = "stop_minute must be a whole number from 0 to 59."
  }
}

variable "stop_grace_minutes" {
  description = <<-EOT
    Minutes between the services being told to scale to zero and the database being
    stopped.

    This stands in for the drain wait that `./scripts/deploy <env> down` performs
    and a universal target cannot: a schedule is a single API call and cannot poll.
    It has to comfortably exceed the worker's `stopTimeout` — the SIGTERM window it
    uses to finish or re-queue an in-flight task — or the database goes while the
    worker is still working.
  EOT
  type        = number
  default     = 15

  validation {
    condition     = var.stop_grace_minutes >= 5
    error_message = "stop_grace_minutes must be at least 5. Anything shorter risks stopping the database while the worker is still inside its SIGTERM window."
  }
}

variable "stop_retry_after_minutes" {
  description = <<-EOT
    Minutes after the first database stop to try a SECOND, independent stop.
    0 (the default) creates no such schedule, and 0 is almost certainly what you
    want.

    It is off by default for two reasons.

    It is nearly redundant: the primary stop's target already carries
    `maximum_event_age_in_seconds = 7200`, so EventBridge Scheduler retries a
    refused stop for two hours by itself. An instance that is `backing-up` or
    `modifying` when the first attempt lands is already covered.

    And it is a trap for anyone working late. A schedule cannot check anything, so
    a second stop fires whether or not the environment is meant to be down. Bring
    the environment back with `./scripts/deploy <env> up` inside this window and
    the retry stops the database again while the services you just started stay
    running -- three tasks crash-looping against a database that is gone, which is
    worse than either the up state or the down state.

    Turn it on only if the two-hour retry window is genuinely being exhausted, and
    know that it widens the period in which a manual `up` gets silently undone.
  EOT
  type        = number
  default     = 0
}

variable "start_hour" {
  description = "Hour (0-23, local) at which the services scale back up."
  type        = number

  validation {
    condition     = var.start_hour >= 0 && var.start_hour <= 23 && floor(var.start_hour) == var.start_hour
    error_message = "start_hour must be a whole number from 0 to 23."
  }
}

variable "start_minute" {
  description = "Minute (0-59) at which the services scale back up."
  type        = number
  default     = 0

  validation {
    condition     = var.start_minute >= 0 && var.start_minute <= 59 && floor(var.start_minute) == var.start_minute
    error_message = "start_minute must be a whole number from 0 to 59."
  }
}

variable "start_lead_minutes" {
  description = <<-EOT
    Minutes before the services scale up that the database is started.

    The database has to be answering first: a task that starts before Postgres does
    fails its readiness check, the ALB pulls it out of rotation, and the deployment
    circuit breaker can roll the whole thing back.

    Measured on staging 2026-08-26, a `db.t4g.small` took ~4.5 minutes from
    `start-db-instance` to `available`, including a restart while enhanced
    monitoring and Performance Insights reconfigured. AWS documents 3-7 minutes as
    the normal range, so 15 leaves roughly 10 minutes of slack.
  EOT
  type        = number
  default     = 15

  validation {
    condition     = var.start_lead_minutes >= 10
    error_message = "start_lead_minutes must be at least 10. An RDS start takes 3-7 minutes and a shorter lead brings the tasks up against a database that is not answering yet."
  }
}

variable "stop_days" {
  description = <<-EOT
    Days the stop runs, as a cron day-of-week field. Default: every day.

    Deliberately wider than `start_days`. Running the stop at weekends costs
    nothing — it fires against an already-stopped instance and fails harmlessly —
    and it means anyone who brings the environment up at a weekend gets it put back
    down that night rather than leaving it running until Monday.

    Not, despite what the ticket originally said, for AWS's seven-day force-start:
    with weekday starts the longest shutdown is about 59 hours, so that rule cannot
    trigger.
  EOT
  type        = string
  default     = "MON-SUN"
}

variable "start_days" {
  description = <<-EOT
    Days the start runs, as a cron day-of-week field. Default: weekdays.

    With the default, Friday's stop and Monday's start leave the environment down
    for the whole weekend — worth more than moving the weekday stop two hours
    earlier would be.
  EOT
  type        = string
  default     = "MON-FRI"
}

variable "enabled" {
  description = <<-EOT
    Whether the schedules are ENABLED or DISABLED.

    An off switch that keeps everything in state: set false and the schedules
    remain, described and reviewable, but never fire. Prefer it to commenting the
    module out, which would delete the role and the dead-letter queue along with
    the schedules and lose whatever the queue was holding.
  EOT
  type        = bool
  default     = true
}

variable "probe_at" {
  description = <<-EOT
    A UTC timestamp, "YYYY-MM-DDTHH:MM:SS", that creates ONE extra one-off schedule
    to prove the universal-target wiring. null (the default) creates nothing.

    It exists because the target input keys are the only part of this module that
    fails silently: `terraform plan` cannot tell a valid key from an invalid one,
    and a wrong one yields a schedule that is created successfully and then does
    nothing every night, with no error anywhere.

    The probe targets `startDBInstance` against an instance that is already
    running, so it cannot change anything. Read the answer from the dead-letter
    queue: an `InvalidDBInstanceState` error means RDS was genuinely called and the
    input shape is right; a validation or parse error means the key was rejected
    before RDS was reached.

    Set it a few minutes ahead, apply, read the queue, then set it back to null.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.probe_at == null || can(regex("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$", var.probe_at))
    error_message = "probe_at must look like \"2026-08-26T04:30:00\" -- a UTC timestamp with no zone suffix, which is the form EventBridge Scheduler's at() expression takes."
  }
}
