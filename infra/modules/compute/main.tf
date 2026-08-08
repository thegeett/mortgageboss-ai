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

  frontend_env = [
    for k in sort(keys(var.frontend_environment_variables)) :
    { name = k, value = var.frontend_environment_variables[k] }
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

  worker_command = [
    "uv", "run", "celery", "-A", "app.tasks.celery_app", "worker", "--loglevel=info",
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

  # The frontend image has NO baked healthcheck (verified: Config.Healthcheck is
  # null), so there is nothing to override. wget is present; curl is not.
  frontend_container_health_command = [
    "CMD-SHELL",
    "wget -q --spider http://127.0.0.1:${var.frontend_port}/ || exit 1",
  ]
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
      # No command override: the image's CMD (`node server.js`) is correct, and it
      # already sets HOSTNAME=0.0.0.0 and PORT=3000 — binding to localhost inside a
      # container makes the health check fail with no useful error.

      portMappings = [{
        containerPort = var.frontend_port
        protocol      = "tcp"
      }]

      environment = local.frontend_env
      # No secrets: the frontend holds no credential. NEXT_PUBLIC_API_URL is baked
      # at BUILD time and cannot be set here at all.

      healthCheck = {
        command     = local.frontend_container_health_command
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }

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
  desired_count   = var.desired_count
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
  desired_count   = var.desired_count
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
  desired_count   = var.desired_count
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
