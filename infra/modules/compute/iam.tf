# IAM — one shared EXECUTION role and three separate TASK roles.
#
# This separation is most of why Fargate was chosen. A single EC2 host would give
# every container the same instance profile, making the api/worker split a diagram
# rather than a control. Per-task roles make it enforceable.
#
#   EXECUTION role — used by the ECS AGENT, before any container process exists:
#                    pull the image, fetch secrets, decrypt them, write logs.
#   TASK role      — used by the APPLICATION at runtime. Deliberately narrow.
#
# No task role has secretsmanager:GetSecretValue: injection happens before the
# process exists, so the application never needs to read a secret itself.

# The account the ARNs below are built against. A data source rather than a variable so
# it cannot be pointed at the wrong account by a mistyped tfvar.
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --------------------------------------------------------------------------- #
# Execution role — shared by all three services
# --------------------------------------------------------------------------- #

resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = merge(var.tags, { Name = "${var.name_prefix}-ecs-execution" })
}

data "aws_iam_policy_document" "execution" {
  # ECR: GetAuthorizationToken is account-wide and CANNOT be resource-scoped — it
  # returns a registry-wide token and AWS rejects any Resource but "*". The pull
  # actions immediately below ARE scoped, so the unscoped statement grants only the
  # ability to obtain a token, not to read any particular repository.
  statement {
    sid       = "ECRAuthToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ECRPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = var.ecr_repository_arns
  }

  # Secrets are injected by the agent. This is the ONLY role that can read them.
  statement {
    sid       = "ReadSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = values(var.secret_arns)
  }

  # Decrypt the secrets with the CMK that protects them. Scoped to that one key.
  statement {
    sid       = "DecryptSecrets"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [var.secrets_kms_key_arn]
  }

  # Log streams inside the pre-created groups. Scoped to those groups' ARNs.
  statement {
    sid    = "WriteLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [for arn in var.log_group_arns : "${arn}:*"]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "${var.name_prefix}-ecs-execution"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# --------------------------------------------------------------------------- #
# Shared fragments for the task roles
# --------------------------------------------------------------------------- #

# ECS Exec. Every action here is a channel-establishment call against the SSM
# messages service, which is not a resource-oriented API — AWS requires "*" and
# rejects any ARN. Gated on var.enable_execute_command so that turning Exec off
# leaves the frontend role with genuinely zero statements.
data "aws_iam_policy_document" "exec_channels" {
  count = var.enable_execute_command ? 1 : 0

  statement {
    sid    = "ECSExecChannels"
    effect = "Allow"
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

locals {
  # Object-level ARN for the documents bucket.
  documents_objects_arn = "${var.documents_bucket_arn}/*"

  # KMS is only involved when the bucket is CMK-encrypted. Under SSE-S3 there is no
  # key to grant against, and attaching an empty statement would be noise.
  bucket_uses_kms = var.documents_bucket_kms_key_arn != null && var.documents_bucket_kms_key_arn != ""
}

# --------------------------------------------------------------------------- #
# API task role
#
# WRITES documents (upload / replace / MISMO import) and READS them back through
# the download proxy. It has NO Bedrock permission of any kind: every one of the
# 13 complete() call sites is reachable only from a Celery task, never from a
# FastAPI route (docs/bedrock-call-sites.md).
# --------------------------------------------------------------------------- #

resource "aws_iam_role" "api_task" {
  name               = "${var.name_prefix}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = merge(var.tags, { Name = "${var.name_prefix}-api-task" })
}

data "aws_iam_policy_document" "api_task" {
  source_policy_documents = var.enable_execute_command ? [data.aws_iam_policy_document.exec_channels[0].json] : []

  # C7 -- the read-only query path. The migrate task definition runs on THIS role, and the
  # query stage runs on that task definition, so the grant lands here rather than on a role
  # of its own. Scoped to ONE database user: it permits authenticating as `mbai_readonly`
  # (a role with no privileges in schema public) and nothing else. It grants no data access
  # by itself -- what the connection can read is decided entirely by the grants in the
  # database, which is where that decision belongs.
  dynamic "statement" {
    for_each = var.db_instance_resource_id == "" ? [] : [1]

    content {
      sid       = "ReadOnlyQueryDbConnect"
      effect    = "Allow"
      actions   = ["rds-db:connect"]
      resources = ["arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.db_instance_resource_id}/${var.readonly_db_user}"]
    }
  }

  # PutObject AND GetObject. Deliberately NO s3:DeleteObject — StorageBackend.delete()
  # has no call site anywhere in the application, consistent with soft-delete
  # throughout, so granting it would widen the role beyond what the code can use.
  statement {
    sid    = "DocumentsReadWrite"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
    ]
    resources = [local.documents_objects_arn]
  }

  # Writing a CMK-encrypted object needs GenerateDataKey; reading one needs Decrypt.
  dynamic "statement" {
    for_each = local.bucket_uses_kms ? [1] : []

    content {
      sid    = "DocumentsBucketKey"
      effect = "Allow"
      actions = [
        "kms:GenerateDataKey",
        "kms:Decrypt",
      ]
      resources = [var.documents_bucket_kms_key_arn]
    }
  }
}

resource "aws_iam_role_policy" "api_task" {
  name   = "${var.name_prefix}-api-task"
  role   = aws_iam_role.api_task.id
  policy = data.aws_iam_policy_document.api_task.json
}

# --------------------------------------------------------------------------- #
# Worker task role
#
# The ONLY role with Bedrock. READ-ONLY on documents — it never writes one, so it
# has no s3:PutObject and needs no kms:GenerateDataKey.
# --------------------------------------------------------------------------- #

resource "aws_iam_role" "worker_task" {
  name               = "${var.name_prefix}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = merge(var.tags, { Name = "${var.name_prefix}-worker-task" })
}

data "aws_iam_policy_document" "worker_task" {
  source_policy_documents = var.enable_execute_command ? [data.aws_iam_policy_document.exec_channels[0].json] : []

  # Scoped to specific model and profile ARNs, never "*".
  #
  # ⚠️ BOTH lists are required. Invoking a cross-region inference profile authorises
  # against the profile ARN *and* the underlying foundation-model ARN in whichever
  # region Bedrock routes to — so the foundation-model list must cover EVERY region
  # in the profile, not only the home region. A short list fails intermittently.
  statement {
    sid    = "InvokeBedrock"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = concat(
      var.bedrock_foundation_model_arns,
      var.bedrock_inference_profile_arns,
    )
  }

  # READ ONLY. No PutObject — the worker reads documents to extract from them and
  # writes its results to the database, never back to the bucket.
  statement {
    sid       = "DocumentsReadOnly"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [local.documents_objects_arn]
  }

  # Decrypt only — no GenerateDataKey, because that is a write-path permission.
  dynamic "statement" {
    for_each = local.bucket_uses_kms ? [1] : []

    content {
      sid       = "DocumentsBucketKeyDecrypt"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = [var.documents_bucket_kms_key_arn]
    }
  }
}

resource "aws_iam_role_policy" "worker_task" {
  name   = "${var.name_prefix}-worker-task"
  role   = aws_iam_role.worker_task.id
  policy = data.aws_iam_policy_document.worker_task.json
}

# --------------------------------------------------------------------------- #
# Frontend task role
#
# Exists so the task definition has one, and so that adding a permission later is
# a policy edit rather than an architecture change. It renders EMPTY unless ECS
# Exec is enabled — the frontend needs no AWS API access to serve pages.
# --------------------------------------------------------------------------- #

resource "aws_iam_role" "frontend_task" {
  name               = "${var.name_prefix}-frontend-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = merge(var.tags, { Name = "${var.name_prefix}-frontend-task" })
}

resource "aws_iam_role_policy" "frontend_task" {
  count = var.enable_execute_command ? 1 : 0

  name   = "${var.name_prefix}-frontend-task"
  role   = aws_iam_role.frontend_task.id
  policy = data.aws_iam_policy_document.exec_channels[0].json
}
