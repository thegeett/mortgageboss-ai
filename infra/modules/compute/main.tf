# Compute — ECS cluster, three Fargate services, and the one-off migration task.

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
  # ⚠️ APPLIED TO EVERY BACKEND CONTAINER, and not environment-specific — it is a
  # property of how the image starts.
  #
  # The image CMD is `uv run ...`, and `uv run` performs a dependency SYNC before
  # executing the command. That sync reaches PyPI. Verified with --network none:
  # plain `uv run` HANGS indefinitely with no output, while `--no-sync` starts in
  # about a second; UV_OFFLINE=1 reveals what it wants ("Failed to download
  # mypy==2.1.0" — a DEV dependency, absent from the runtime venv).
  #
  # In a VPC whose only egress is interface endpoints there is no route to PyPI, so
  # the sync does not fail — it hangs. The container never starts, emits NO
  # application log line, and with ECS Exec off there is no shell. The circuit
  # breaker then rolls back, so the visible symptom is "tasks keep dying" with
  # nothing explaining why.
  #
  # Setting it here eliminates the dependency rather than routing around it, and
  # needs no image or code change. The runtime then depends on the baked
  # /app/.venv being complete — the correct invariant for a container, which should
  # not be mutating its own dependencies at boot.
  runtime_env = {
    UV_NO_SYNC = "1"
  }

  merged_api_env = merge(local.runtime_env, var.environment_variables)

  # Sorted so the rendered task definitions are stable across plans — an unsorted
  # map would reorder the environment[] array and show a spurious diff every time.
  api_env = [
    for k in sort(keys(local.merged_api_env)) :
    { name = k, value = local.merged_api_env[k] }
  ]

  # ⚠️ HOSTNAME=0.0.0.0 IS LOAD-BEARING, and it is set HERE rather than left to the
  # image, because the image's value does not survive ECS.
  #
  # Next.js standalone `server.js` binds to `process.env.HOSTNAME`. The Dockerfile
  # sets `ENV HOSTNAME=0.0.0.0` and that wins under a plain `docker run` — but in
  # Fargate the agent injects the container's own hostname, so the app bound to the
  # task ENI address alone:
  #
  #   local docker : Network: http://0.0.0.0:3000
  #   Fargate      : Network: http://10.30.47.218:3000      <- one interface only
  #
  # Which produced a failure that looks like nothing at all: the ALB connects to the
  # ENI address, so the target registered HEALTHY and the site kept serving, while
  # anything on the loopback got connection refused. The container health check
  # (127.0.0.1) failed every time and ECS killed the task ~132s in, over and over,
  # until the circuit breaker failed the deployment.
  #
  # Setting it explicitly in the container definition puts it back on all
  # interfaces. Merged UNDER the caller's map so an environment can still override
  # it deliberately.
  frontend_env = [
    for k in sort(keys(merge({ HOSTNAME = "0.0.0.0" }, var.frontend_environment_variables))) :
    { name = k, value = merge({ HOSTNAME = "0.0.0.0" }, var.frontend_environment_variables)[k] }
  ]

  task_secrets = [
    for k in sort(keys(var.secret_arns)) :
    { name = k, valueFrom = var.secret_arns[k] }
  ]

  # The API runs the SAME image as the worker with a different command. C1's image
  # CMD is the Celery worker, so the API must override it.
  api_command = [
    "uv", "run", "uvicorn", "app.main:app",
    "--host", "0.0.0.0",
    "--port", tostring(var.api_port),
  ]

  # --concurrency is DECLARED, never inherited (LP-629). Without it Celery falls back to
  # os.cpu_count(), so a 1024-CPU task silently ran ONE job at a time and every document
  # extraction, verification run and needs update in the environment queued behind each
  # other. Measured before the fix: six documents from one upload took 2m53s of strictly
  # serial work against a ~35s critical path.
  worker_command = [
    "uv", "run", "celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info",
    "--concurrency=${var.worker_concurrency}",
  ]

  migration_command = ["uv", "run", "alembic", "upgrade", "head"]

  # ⚠️ The image bakes a Celery `inspect ping` HEALTHCHECK (verified with
  # `docker image inspect`). It is correct for the worker and WRONG for the API,
  # which runs no Celery node — an API container that does not override it sits
  # UNHEALTHY FOREVER while serving traffic perfectly.
  #
  # curl and wget are BOTH absent from the backend image (verified), so the check
  # uses python3, which is present. urllib raises on a non-2xx status, so a failure
  # is a non-zero exit without needing an explicit status comparison.
  api_container_health_command = [
    "CMD-SHELL",
    "python3 -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:${var.api_port}${var.health_check_path}', timeout=3)\" || exit 1",
  ]

  # Kept from C1: the worker has no HTTP surface, so ECS cannot otherwise tell
  # "alive" from "alive but not consuming". A worker that lost its broker looks
  # healthy and silently stops processing.
  worker_container_health_command = [
    "CMD-SHELL",
    "uv run celery -A app.tasks.celery_app inspect ping -d celery@$HOSTNAME || exit 1",
  ]

  # ⚠️ THE FRONTEND HAS NO CONTAINER HEALTH CHECK, DELIBERATELY.
  #
  # It had one (`wget -q --spider http://127.0.0.1:3000/`) and it caused an outage
  # rather than catching one — see the HOSTNAME note above. The command itself was
  # never the problem: the image is Alpine, `wget` is present at /usr/bin/wget
  # (BusyBox), and against a correctly-bound server it exits 0. It failed because
  # the server was not on the loopback.
  #
  # It is not being repaired, because for a service behind a load balancer it is
  # redundant: the ALB target group already probes `/` with matcher 200-399 and
  # deregisters a task that stops answering. Two checks of the same liveness, and
  # only one of them can kill the task.
  #
  # ⚠️ The WORKER's check is NOT redundant and stays — it has no ALB in front of it,
  # so `celery inspect ping` is the only way ECS can tell "alive" from "alive but
  # not consuming". That reasoning does not transfer to a load-balanced service.
  #
  # If one is ever wanted back here, use the runtime rather than a shell utility —
  # `node` is guaranteed present in a Node image, a BusyBox applet is not:
  #
  #   node -e "require('http').get('http://127.0.0.1:3000/',r=>process.exit(r.statusCode<400?0:1)).on('error',()=>process.exit(1))"
  #
  # (verified working inside the deployed image). Only add it back after confirming
  # the task actually binds 0.0.0.0, or it will reproduce the same crash loop.
}

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix

  setting {
    name  = "containerInsights"
    value = var.enable_container_insights ? "enabled" : "disabled"
  }

  tags = merge(var.tags, { Name = var.name_prefix })
}

# FARGATE, deliberately NOT FARGATE_SPOT — see the module README.
resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 0
  }
}

# --------------------------------------------------------------------------- #
# Task definitions
# --------------------------------------------------------------------------- #

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.api_image
      essential = true
      command   = local.api_command

      portMappings = [{
        containerPort = var.api_port
        protocol      = "tcp"
      }]

      environment = local.api_env
      secrets     = local.task_secrets

      healthCheck = {
        command     = local.api_container_health_command
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.log_group_names["api"]
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    }
  ])

  tags = merge(var.tags, { Name = "${var.name_prefix}-api" })
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.api_image # SAME image as the API, different command (C1)
      essential = true
      command   = local.worker_command

      # No portMappings: the worker has no inbound path at all.

      environment = local.api_env
      secrets     = local.task_secrets

      # Gives Celery time to finish the task in flight after SIGTERM instead of
      # losing it. Effective because `uv run` forwards the signal (verified).
      stopTimeout = var.worker_stop_timeout_seconds

      healthCheck = {
        command  = local.worker_container_health_command
        interval = 30
        timeout  = 10
        retries  = 3
        # Generous: a cold start plus the first database connection takes a while,
        # and a check that fires too early kills a task that was merely starting.
        startPeriod = 120
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.log_group_names["worker"]
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "worker"
        }
      }
    }
  ])

  tags = merge(var.tags, { Name = "${var.name_prefix}-worker" })
}

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${var.name_prefix}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.frontend_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = var.frontend_image
      essential = true
      # No command override: the image's CMD (`node server.js`) is correct.
      #
      # ⚠️ The image also sets ENV HOSTNAME=0.0.0.0 and PORT=3000 — but ECS injects
      # its own HOSTNAME at runtime and the image's value loses. That is why
      # HOSTNAME is set explicitly in local.frontend_env; see the note there.

      portMappings = [{
        containerPort = var.frontend_port
        protocol      = "tcp"
      }]

      environment = local.frontend_env
      # No secrets: the frontend holds no credential. NEXT_PUBLIC_API_URL is baked
      # at BUILD time and cannot be set here at all.

      # No healthCheck — see the note in locals. The ALB target group is the
      # liveness check for this service.

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.log_group_names["frontend"]
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "frontend"
        }
      }
    }
  ])

  tags = merge(var.tags, { Name = "${var.name_prefix}-frontend" })
}

# --------------------------------------------------------------------------- #
# Migration task — RUN MANUALLY, never as a service.
#
# Alembic must not run at container start: three tasks starting concurrently
# would race on the same migration, and a failure would crash-loop the service
# rather than failing one visible job.
#
# Uses the API task role (it needs no S3 or Bedrock access, but reusing the role
# avoids inventing a fourth) and the shared execution role, so DATABASE_URL is
# injected the same way. alembic/env.py reads the same asyncpg URL, so the same
# `?ssl=require` spelling applies.
# --------------------------------------------------------------------------- #

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([
    {
      name      = "migrate"
      image     = var.api_image
      essential = true
      command   = local.migration_command

      environment = local.api_env
      secrets     = local.task_secrets

      # No healthCheck: this is a run-to-completion task, not a long-lived one.
      # The baked Celery healthcheck does not apply to a task run via run-task.

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.log_group_names["api"]
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "migrate"
        }
      }
    }
  ])

  tags = merge(var.tags, { Name = "${var.name_prefix}-migrate" })
}

# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #

resource "aws_ecs_service" "api" {
  name            = "${var.name_prefix}-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  enable_execute_command = var.enable_execute_command

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.api_port
  }

  # Without rollback a bad task definition loops: ECS keeps launching tasks that
  # fail their health check until someone notices.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # The task cannot register until the listener exists, and a service created
  # first fails its initial deployment.
  depends_on = [aws_lb_listener.http]

  tags = merge(var.tags, { Name = "${var.name_prefix}-api" })
}

# NO load_balancer block, and no target group. The worker's only inbound path
# would be the ALB, and it deliberately has none — it consumes from Redis.
resource "aws_ecs_service" "worker" {
  name            = "${var.name_prefix}-worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  enable_execute_command = var.enable_execute_command

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-worker" })
}

resource "aws_ecs_service" "frontend" {
  name            = "${var.name_prefix}-frontend"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.frontend_desired_count
  launch_type     = "FARGATE"

  enable_execute_command = var.enable_execute_command

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_tasks_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = var.frontend_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.http]

  tags = merge(var.tags, { Name = "${var.name_prefix}-frontend" })
}
