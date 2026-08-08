output "alb_dns_name" {
  description = "Public DNS name of the load balancer. The application is reachable here over HTTP until C4 adds TLS."
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  description = "Hosted zone id of the load balancer — C4 needs it for the alias record."
  value       = aws_lb.this.zone_id
}

output "alb_arn" {
  description = "Load balancer ARN."
  value       = aws_lb.this.arn
}

output "http_listener_arn" {
  description = "HTTP listener ARN — C4 attaches the HTTPS listener alongside it."
  value       = aws_lb_listener.http.arn
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.this.arn
}

output "service_names" {
  description = "Map of service key to ECS service name."
  value = {
    api      = aws_ecs_service.api.name
    worker   = aws_ecs_service.worker.name
    frontend = aws_ecs_service.frontend.name
  }
}

output "task_definition_arns" {
  description = "Map of task key to task definition ARN, including the run-once migration task."
  value = {
    api      = aws_ecs_task_definition.api.arn
    worker   = aws_ecs_task_definition.worker.arn
    frontend = aws_ecs_task_definition.frontend.arn
    migrate  = aws_ecs_task_definition.migrate.arn
  }
}

output "task_role_arns" {
  description = "Map of task key to task role ARN. Identifiers, not credentials."
  value = {
    api      = aws_iam_role.api_task.arn
    worker   = aws_iam_role.worker_task.arn
    frontend = aws_iam_role.frontend_task.arn
  }
}

output "execution_role_arn" {
  description = "Shared ECS execution role ARN."
  value       = aws_iam_role.execution.arn
}

output "target_group_arns" {
  description = "Map of target group key to ARN."
  value = {
    api      = aws_lb_target_group.api.arn
    frontend = aws_lb_target_group.frontend.arn
  }
}

output "migration_run_task_command" {
  description = <<-EOT
    Ready-to-paste `aws ecs run-task` invocation for the Alembic migration.

    Run it AFTER the secrets are populated and BEFORE scaling the services up — a
    service started against an un-migrated database fails in a way that looks like
    an application bug.
  EOT
  value = join(" ", [
    "aws ecs run-task",
    "--cluster ${aws_ecs_cluster.this.name}",
    "--task-definition ${aws_ecs_task_definition.migrate.family}",
    "--launch-type FARGATE",
    "--network-configuration 'awsvpcConfiguration={subnets=[${join(",", var.private_subnet_ids)}],securityGroups=[${var.ecs_tasks_security_group_id}],assignPublicIp=DISABLED}'",
  ])
}

output "execute_command_invocations" {
  description = <<-EOT
    Map of service key to its `aws ecs execute-command` invocation. Requires the
    Session Manager plugin locally and enable_execute_command = true.

    Each needs --task <task-id>, which changes on every deployment; list them with
    `aws ecs list-tasks --cluster <cluster> --service-name <service>`.
  EOT
  value = var.enable_execute_command ? {
    for k, v in {
      api      = aws_ecs_service.api.name
      worker   = aws_ecs_service.worker.name
      frontend = aws_ecs_service.frontend.name
      } : k => join(" ", [
        "aws ecs execute-command",
        "--cluster ${aws_ecs_cluster.this.name}",
        "--task <task-id>",
        "--container ${k}",
        "--interactive",
        "--command /bin/sh",
    ])
  } : {}
}

output "cognito_user_pool_id" {
  description = "User pool id, or null when Cognito is disabled. An identifier, not a credential — needed for admin-create-user."
  value       = var.enable_cognito ? aws_cognito_user_pool.this[0].id : null
}

output "cognito_hosted_ui_domain" {
  description = "Cognito hosted UI domain, or null when disabled."
  value       = var.enable_cognito ? aws_cognito_user_pool_domain.this[0].domain : null
}
