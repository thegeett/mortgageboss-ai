# scheduler

Takes the environment offline overnight and at weekends, and brings it back.

Eight EventBridge Scheduler schedules that scale the ECS services to zero and stop
the RDS instance at night, then reverse it on a weekday morning. No Lambda and no
application code: Scheduler's **universal targets** call the AWS SDK directly, so
each target is an ARN plus a JSON request body.

Free at this volume — 14M invocations a month are included and this uses about 250.

Background, cost arithmetic and the alternatives that were rejected:
[`docs/tickets/LP-630.md`](../../../docs/tickets/LP-630.md).

## What fires, and when

With the staging defaults, in `America/New_York`:

| Cron | Days | Target |
| --- | --- | --- |
| `0 22` ×3 | Mon–Sun | `ecs:updateService` → `DesiredCount = 0` |
| `15 22` | Mon–Sun | `rds:stopDBInstance` |
| `45 8` | Mon–Fri | `rds:startDBInstance` |
| `0 9` ×3 | Mon–Fri | `ecs:updateService` → `DesiredCount = N` |

`terraform output shutdown_schedule` prints this for the values actually applied.
Read that rather than reassembling it: the database times are *derived* from the
service times plus a grace, and are not written down in tfvars.

**One schedule has exactly one target**, which is why three services means three
schedules each way rather than one with three targets.

### Why the stop runs at weekends but the start does not

Friday 22:00 to Monday 09:00 is one continuous shutdown, and the Saturday and
Sunday stops fire against an already-stopped instance and fail harmlessly.

They are worth keeping for one reason: **anyone who brings the environment up at a
weekend gets it put back down that night.** Without them, a Saturday
`./scripts/deploy <env> up` runs until Monday.

They are *not* there for AWS's seven-day force-start, which the ticket originally
gave as the rationale. That does not apply under this schedule: with
`start_days = MON-FRI` the longest continuous shutdown is about 59 hours, so seven
days is unreachable. It becomes relevant only if the start is narrowed or the
schedules are disabled for a long break — and if they are disabled, the weekend
stops are not firing either.

## What this is not

It is **not** the equivalent of `./scripts/deploy <env> down`.

That command scales, waits for the tasks to actually stop, checks that no one-off
task is running, and only then stops the database. A universal target is a single
API call — it cannot wait, cannot check, and cannot refuse.

So `stop_grace_minutes` (15) stands in for the drain wait. That is comfortable: an
idle worker drains in about 10 seconds, and a busy one within its 120-second
`stopTimeout`. What it cannot cover is a **one-off task** — a `migrate`,
`backfill-mismo` or `verify` running at 22:00 keeps its database connection until
22:15 and then loses it.

That is accepted deliberately. The blast radius is one interrupted staging job
overnight; closing it properly needs a Lambda or a container running the deploy
script, which is a lot of machinery for a job that runs once a day. **`down` and
`up` stay the safe path when a person is driving.**

## Mixing the schedule with `down` and `up` by hand

Safe in both directions. The schedules act unconditionally, and acting on a
resource that is already in the wanted state is either a silent no-op or a benign
error:

| You did | Then the schedule fires | Result |
| --- | --- | --- |
| `up` after the night's stop | `startDBInstance` at 08:45 | Fails `InvalidDBInstanceState`, lands in the DLQ. Instance untouched. |
| `up` after the night's stop | `updateService` = N at 09:00 | Succeeds, no-op. Changing only `desiredCount` creates no deployment, and setting it to its current value changes nothing. |
| `down` during the day | `updateService` = 0 at 22:00 | Succeeds, no-op. |
| `down` during the day | `stopDBInstance` at 22:15 | Fails `InvalidDBInstanceState`, lands in the DLQ. Instance untouched. |

Two things follow from that.

**A manual `down` does not keep the environment down.** The next weekday morning
brings it back. To hold it down for longer — a holiday, an investigation — set
`enabled = false` rather than relying on `down`.

**Do not add a second stop schedule** (`stop_retry_after_minutes`). It is the one
combination that genuinely hurts: bring the environment up to work late, and a
later stop takes the database away while the services you just started stay
running. Three tasks crash-looping against a database that is gone is worse than
either the up state or the down state. The primary stop already retries for two
hours on its own, which covers the case a second schedule was meant to.

## Depends on Phase A

The services must carry `lifecycle { ignore_changes = [desired_count] }`
([`../compute/README.md`](../compute/README.md)). Without it the next
`terraform apply` after a 22:00 scale-down restores all three services from tfvars
and the environment runs all night while every artifact says it should not.

## The dead-letter queue

**A schedule that fails is silent.** There is no console banner and no log group;
the invocation simply does not happen. The first anyone knows is a bill that did
not fall, or an environment that did not come back.

So every target has a DLQ, and every failure lands there carrying the API's own
error code and message:

```bash
aws sqs receive-message \
  --queue-url "$(terraform output -raw shutdown_dlq_url)" \
  --message-attribute-names All --max-number-of-messages 10
```

### What is expected in there, and what is not

The queue is only a useful signal if you know what belongs in it. Two of these
schedules routinely act on a resource that is already in the state they want,
which the AWS API treats as an error.

| Message | Meaning |
| --- | --- |
| `InvalidDBInstanceState` from **stop-database**, at weekends | Expected. The environment was already down from Friday, so Saturday's and Sunday's stops are no-ops. |
| `InvalidDBInstanceState` from **stop-database**, on a weeknight | Expected if someone had already run `./scripts/deploy <env> down` by hand. |
| `InvalidDBInstanceState` from **start-database** | Expected if someone ran `up` by hand before the morning schedule fired. |
| Anything from **stop-service** or **start-service** | Not expected. `ecs:UpdateService` succeeds even when the count is already correct, so a message here is a real fault — a renamed service, a revoked permission, a wrong cluster. |
| A validation or parse error from any target | Not expected, and the serious one: the target input shape is wrong, so that schedule has never done anything. See the probe below. |

So read the error code, not the message count. `InvalidDBInstanceState` is the
sound of the system working; anything else is worth opening.

## Verifying the wiring without waiting for 22:00

The universal-target **input keys** are the one thing here that `terraform plan`
cannot check. RDS is the trap: the API reference spells the parameter
`DBInstanceIdentifier`, the SDK spells it `DbInstanceIdentifier`, and Scheduler
wants the SDK's spelling. Get it wrong and the schedule is created happily, plans
clean, and does nothing every night.

`probe_at` settles it. Set it to a UTC timestamp a few minutes ahead and apply:

```hcl
shutdown_probe_at = "2026-08-26T04:30:00"
```

It creates one extra one-off schedule targeting `startDBInstance` against an
instance that is **already running**, so it cannot change anything. Wait for the
time to pass, then read the queue. The two outcomes are distinguishable by the
error alone:

| Error in the DLQ | Meaning |
| --- | --- |
| `InvalidDBInstanceState` | The key was accepted and RDS was really called. **The wiring works.** |
| a validation or parse error | The key was rejected before RDS was reached. The spelling is wrong. |

Set it back to `null` and apply again to remove it.

## Turning it off

Set `enabled = false`. The schedules stay in state — described, reviewable,
diffable — but never fire.

Prefer that to commenting the module out, which would delete the execution role
and the dead-letter queue along with the schedules, and lose whatever the queue
was holding.

## RDS backup and maintenance windows

Not this module's resources, but its problem. Both windows are UTC and RDS will
not take a timezone, so an AWS-assigned window commonly lands inside a nightly
shutdown — and a stopped instance takes no automated backup and receives no
maintenance.

`envs/staging` pins them accordingly. In Eastern the running window is 13:00–02:00
UTC under EDT and 14:00–03:00 under EST, so only **14:00–02:00 UTC** is inside
both, and AWS requires the two windows not to overlap:

```hcl
rds_backup_window      = "14:30-15:00"          # 10:30 EDT / 09:30 EST
rds_maintenance_window = "wed:15:30-wed:16:00"  # 11:30 EDT / 10:30 EST
```

The trade being made: a maintenance reboot now lands mid-morning on a Wednesday
rather than overnight. That is disruptive once a week on a running staging
environment, and still the right side of the trade — the alternative is that
maintenance never applies and pending updates accumulate until the seven-day rule
applies them all unattended.

## Choosing the timezone

`timezone` takes an IANA name and Scheduler applies DST itself, so `22:00` stays
`22:00` across both transitions without a second set of schedules.

Pick the zone the people using the environment are in — it decides who finds it
dark. **Never infer it from `aws_region`:** that is where the infrastructure runs,
not where anyone works. Staging is `America/New_York`.
