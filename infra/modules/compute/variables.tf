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

variable "api_root_path_patterns" {
  description = <<-EOT
    Root-level paths routed to the API rather than the frontend.

    The application serves its health endpoints at the ROOT (/health, /health/live,
    /health/ready), not under the /api/v1 prefix the feature routers use, so they
    need an explicit rule or they fall through to the frontend.

    ⚠️ FIVE VALUES MAXIMUM. An ALB counts condition values ACROSS THE WHOLE RULE,
    not per condition block, and the limit is 5. The validation below is what makes
    a sixth entry a plan-time error rather than an apply-time ValidationError
    partway through creating an environment.

    ⚠️ FastAPI's /docs, /docs/*, /redoc and /openapi.json are deliberately NOT here.
    They are the interactive documentation and the OpenAPI schema: a complete,
    machine-readable map of every endpoint, its parameters and its response shapes.
    In an environment holding real borrower files there is no reason to route them
    at all. Cognito would gate them from phase 2 onward, but "authenticated users
    can enumerate the entire API surface" is a weaker position than "the load
    balancer has no route to it", and it costs nothing to hold the stronger one.
    Unrouted, they reach the frontend's default action and 404 — the API still
    serves them internally, so `curl` from inside the VPC is unaffected.

    A future environment that wants them (a public demo, say) adds them here
    without editing this module — and gets the 5-value limit checked for it.
  EOT
  type        = list(string)
  default     = ["/health", "/health/*"]

  validation {
    condition     = length(var.api_root_path_patterns) <= 5
    error_message = "api_root_path_patterns accepts at most 5 entries: an ALB listener rule permits only 5 condition values and regex values in total, counted across every condition block in the rule. Split the extras into a second aws_lb_listener_rule with its own priority, or drop them."
  }

  validation {
    condition     = length(var.api_root_path_patterns) > 0
    error_message = "api_root_path_patterns must not be empty: an ALB path_pattern condition requires at least one value, and an empty list fails at apply time rather than here."
  }
}

# --- TLS and authentication (C4) -------------------------------------------- #

variable "enable_tls" {
  description = <<-EOT
    Create the HTTPS listener and turn port 80 into a redirect.

    ⚠️ PHASE GATE. false on the first apply (no certificate exists yet); true on the
    second, once DNS delegation is live and ACM has issued.
  EOT
  type        = bool
  default     = false
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the HTTPS listener. Required when enable_tls is true."
  type        = string
  default     = null
}

variable "ssl_policy" {
  description = <<-EOT
    ALB security policy for the HTTPS listener.

    TLS 1.3 with a 1.2 floor: 1.3 removes the negotiated-cipher and renegotiation
    downgrade classes outright, while keeping 1.2 available for clients that cannot
    do 1.3.
  EOT
  type        = string
  default     = "ELBSecurityPolicy-TLS13-1-2-2021-06"
}

variable "domain_name" {
  description = <<-EOT
    Public domain the environment is served on. Used to build the Cognito callback
    URL — deliberately NOT the ALB's generated DNS name, which would create a cycle
    between the listener and the user pool.
  EOT
  type        = string
  default     = null
}

variable "enable_cognito" {
  description = <<-EOT
    Put an authenticate-cognito action in front of every listener rule.

    ⚠️ Requires enable_tls — an ALB cannot attach this action to an HTTP listener.
    A precondition fails the plan rather than letting the environment come up
    unauthenticated while appearing configured.
  EOT
  type        = bool
  default     = false
}

variable "cognito_domain_prefix" {
  description = "Prefix for the Cognito hosted UI domain. Globally unique across AWS."
  type        = string
  default     = null
}

variable "cognito_mfa_configuration" {
  description = <<-EOT
    "OFF", "OPTIONAL", or "ON".

    OPTIONAL rather than ON by default: ON before any user exists locks out the
    first admin-created account. Turn it ON once users are enrolled — it is on the
    pre-handover checklist.
  EOT
  type        = string
  default     = "OPTIONAL"

  validation {
    condition     = contains(["OFF", "OPTIONAL", "ON"], var.cognito_mfa_configuration)
    error_message = "cognito_mfa_configuration must be OFF, OPTIONAL, or ON."
  }
}

variable "cognito_session_timeout_seconds" {
  description = <<-EOT
    ALB authentication session lifetime.

    ⚠️ DELIBERATELY LONG. When a session expires mid-use, an in-flight fetch()
    receives a 302 toward the hosted login page — which browser JavaScript cannot
    follow, so the application fails in ways that look like application bugs rather
    than an expired login. A long session moves expiry to BETWEEN visits.
  EOT
  type        = number
  default     = 604800 # 7 days
}

variable "cognito_refresh_token_validity_days" {
  description = <<-EOT
    Refresh token lifetime in days. Must EXCEED the session timeout, or the ALB
    cannot silently renew and the user is bounced mid-session anyway.
  EOT
  type        = number
  default     = 30
}
