# Compute module inputs.
#
# Environment-agnostic per §6b: no account id, no region literal, no environment
# name, no `mbai-*` string. Everything that differs between environments arrives
# here as a variable with NO default. Defaults exist only for values that are
# genuinely universal (container ports, the health path the application serves).

variable "name_prefix" {
  description = "Prefix every resource name derives from."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "aws_region" {
  description = "Region, used for the awslogs driver's awslogs-region option. Never hardcoded here."
  type        = string
}

# --- Networking ------------------------------------------------------------ #

variable "vpc_id" {
  description = "VPC the target groups attach to."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the internet-facing load balancer."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets for the tasks. Tasks get no public IP."
  type        = list(string)
}

variable "alb_security_group_id" {
  description = "Security group for the load balancer (C2)."
  type        = string
}

variable "ecs_tasks_security_group_id" {
  description = "Security group for the tasks (C2) — admits the application ports from the ALB only."
  type        = string
}

# --- Images ---------------------------------------------------------------- #

variable "api_image" {
  description = <<-EOT
    Fully-qualified image URI for the backend. The api and the worker run the SAME
    image with different commands — C1 established one image for both — so there is
    deliberately no separate worker_image.
  EOT
  type        = string
}

variable "frontend_image" {
  description = "Fully-qualified image URI for the frontend."
  type        = string
}

variable "cpu_architecture" {
  description = <<-EOT
    Fargate runtime platform CPU architecture: "ARM64" or "X86_64".

    ⚠️ MUST match the architecture of the images actually built. A mismatch fails
    with `exec format error` — the task starts, dies immediately, and the message
    appears only in the CloudWatch log stream, never in the ECS console's service
    events. Verify with:
      docker image inspect <image> --format '{{.Architecture}}'
  EOT
  type        = string

  validation {
    condition     = contains(["ARM64", "X86_64"], var.cpu_architecture)
    error_message = "cpu_architecture must be exactly \"ARM64\" or \"X86_64\"."
  }
}

# --- Task sizing ----------------------------------------------------------- #

variable "api_cpu" {
  description = "API task CPU units."
  type        = number
}

variable "api_memory" {
  description = "API task memory (MiB)."
  type        = number
}

variable "worker_cpu" {
  description = "Worker task CPU units."
  type        = number
}

variable "worker_memory" {
  description = <<-EOT
    Worker task memory (MiB). Deliberately larger than the API's: extraction holds a
    whole PDF in memory while base64-encoding it, against a 50 MB upload cap.
  EOT
  type        = number
}

variable "frontend_cpu" {
  description = "Frontend task CPU units."
  type        = number
}

variable "frontend_memory" {
  description = "Frontend task memory (MiB)."
  type        = number
}

variable "desired_count" {
  description = <<-EOT
    Task count for every service. There is deliberately NO autoscaling — see the
    module README.

    ⚠️ Raising this for the worker requires DIVIDING ai_requests_per_minute_bedrock
    by the new count: that limiter is per-process, so N tasks pace at N x the value.
  EOT
  type        = number
}

# --- Configuration --------------------------------------------------------- #

variable "environment_variables" {
  description = <<-EOT
    Plain (non-secret) environment variables applied to the api and worker
    containers. Several have application defaults that silently behave like local
    development — see the module README.
  EOT
  type        = map(string)
}

variable "frontend_environment_variables" {
  description = "Plain environment variables for the frontend container."
  type        = map(string)
}

variable "secret_arns" {
  description = <<-EOT
    Map of ENVIRONMENT VARIABLE NAME to Secrets Manager ARN, injected by the ECS
    AGENT via the execution role before the container process exists.

    No task role needs secretsmanager:GetSecretValue for this reason.
  EOT
  type        = map(string)
}

# --- Logging --------------------------------------------------------------- #

variable "log_group_names" {
  description = <<-EOT
    Map of service key ("api" / "worker" / "frontend") to the CloudWatch log group
    name created in the data module. Passed in rather than created here so ECS never
    auto-creates a never-expire group.
  EOT
  type        = map(string)
}

# --- IAM scoping ----------------------------------------------------------- #

variable "ecr_repository_arns" {
  description = <<-EOT
    Repository ARNs the EXECUTION role may pull from. Scoped rather than "*" so the
    role cannot read every repository in the account.
  EOT
  type        = list(string)
}

variable "log_group_arns" {
  description = <<-EOT
    ARNs of the pre-created log groups. The execution role's log statement is scoped
    to "<arn>:*" — the streams inside these groups and nothing else.
  EOT
  type        = list(string)
}

variable "documents_bucket_arn" {
  description = "ARN of the hand-created documents bucket. Object permissions are scoped to <arn>/*."
  type        = string
}

variable "documents_bucket_kms_key_arn" {
  description = <<-EOT
    CMK protecting the documents bucket, or null when the bucket uses SSE-S3.

    When null, no KMS statement is attached to the task roles — SSE-S3 needs none.
    Getting this wrong in the "should have been set" direction fails at the first
    upload with an opaque AccessDenied from S3, not from KMS.
  EOT
  type        = string
}

variable "secrets_kms_key_arn" {
  description = "CMK protecting the Secrets Manager secrets — the EXECUTION role decrypts with it."
  type        = string
}

variable "bedrock_foundation_model_arns" {
  description = <<-EOT
    Foundation-model ARNs the worker may invoke.

    ⚠️ A cross-region inference profile requires the foundation-model ARN in EVERY
    region the profile can route to, not just the home region. Omitting one produces
    an INTERMITTENT AccessDeniedException — it fails only when Bedrock happens to
    route to the missing region.
  EOT
  type        = list(string)
}

variable "bedrock_inference_profile_arns" {
  description = "Inference-profile ARNs the worker may invoke, alongside the foundation models above."
  type        = list(string)
}

# --- Behaviour toggles ----------------------------------------------------- #

variable "enable_container_insights" {
  description = "Container Insights on the cluster. Costs money per metric; off for a cost-sensitive environment."
  type        = bool
}

variable "enable_execute_command" {
  description = <<-EOT
    Allow `aws ecs execute-command` (ECS Exec) into running tasks.

    Fargate has no SSH, so without this the only diagnostic surface is CloudWatch
    logs — and several failure modes here produce no log line at all.

    ⚠️ This is a PRODUCTION ACCESS PATH: it grants a shell inside a task holding
    borrower data. Appropriate for a throwaway environment, and it should be gated
    or disabled where real NPI lives. When false, the ssmmessages statements are
    omitted from every task role, so the frontend role ends up genuinely empty.
  EOT
  type        = bool
}

variable "enable_alb_access_logs" {
  description = "Write ALB access logs to S3. Requires alb_access_logs_bucket when true."
  type        = bool
}

variable "alb_access_logs_bucket" {
  description = "Bucket for ALB access logs; ignored when enable_alb_access_logs is false."
  type        = string
}

variable "worker_stop_timeout_seconds" {
  description = <<-EOT
    Grace period between SIGTERM and SIGKILL for the worker container.

    A Celery worker killed mid-extraction loses the task. 120 is the Fargate maximum.
    Verified empirically that `uv run` forwards SIGTERM to its child, so this is
    effective rather than decorative — see the module README.
  EOT
  type        = number

  validation {
    condition     = var.worker_stop_timeout_seconds > 0 && var.worker_stop_timeout_seconds <= 120
    error_message = "Fargate permits a stopTimeout between 1 and 120 seconds."
  }
}

variable "deregistration_delay_seconds" {
  description = "Target group draining period. The AWS default of 300s makes every deploy slow."
  type        = number
}

# --- Universal values (defaults permitted — not environment-specific) ------- #

variable "api_port" {
  description = "Port the API listens on. A property of the application, identical in every environment."
  type        = number
  default     = 8000
}

variable "frontend_port" {
  description = "Port the frontend listens on. A property of the application."
  type        = number
  default     = 3000
}

variable "health_check_path" {
  description = <<-EOT
    Liveness path for the API target group.

    /health/live is DEPENDENCY-FREE by design. The sibling /health and /health/ready
    both return 503 when Postgres or Redis is unreachable; pointing a target group at
    either turns a database blip into a total outage, because every replacement task
    fails its check too.
  EOT
  type        = string
  default     = "/health/live"
}
