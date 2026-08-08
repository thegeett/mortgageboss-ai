# Registry — ECR repositories for the container images.
#
# TWO repositories, not three. C1 established that the API and the Celery worker
# run the SAME image with different commands, so a third `worker` repository would
# hold byte-identical copies of the `api` images — extra storage, and a standing
# opportunity for the two to drift out of sync at deploy time.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_ecr_repository" "this" {
  for_each = toset(var.repository_names)

  name = each.value

  # A tag must always mean the same bytes. Mutable tags make "which build is
  # running?" unanswerable after the fact, and make a rollback a guess.
  image_tag_mutability = "IMMUTABLE"

  force_delete = var.force_delete

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = merge(var.tags, { Name = each.value })
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name

  # Rule order matters: ECR evaluates by ascending priority and applies the first
  # match. Untagged images are expired first (rule 1) so the "keep last N" count in
  # rule 3 is not consumed by garbage.
  #
  # Rule 2 is the PROTECTED tier and exists because this registry is shared. The
  # count in rule 3 is global across every environment, so a CI pipeline pushing
  # per commit reaches the ceiling in days and evicts the OLDEST image — which is
  # exactly where a long-lived promoted tag sits. The symptom would not be a failed
  # deploy but a deferred one: the environment running that tag cannot launch a
  # replacement task or scale out, failing with CannotPullContainerError long after
  # the push that caused it.
  #
  # Rule 2 therefore holds a much deeper history for the promotion prefixes, and
  # because it matches FIRST those images never reach rule 3's count at all.
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.untagged_expire_days} days."
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_expire_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep ${var.keep_last_protected_images} promoted images (${join(", ", var.protected_tag_prefixes)})."
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = var.protected_tag_prefixes
          countType     = "imageCountMoreThan"
          countNumber   = var.keep_last_protected_images
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 3
        description  = "Keep only the last ${var.keep_last_images} remaining images."
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.keep_last_images
        }
        action = { type = "expire" }
      },
    ]
  })
}

# Cross-account pull.
#
# Created only when pull_account_ids is non-empty, so a single-account deployment
# carries no policy at all rather than one granting nothing.
#
# ecr:GetAuthorizationToken is deliberately ABSENT: it is an account-level action
# that the PULLING account grants its own principals, and it cannot be granted by a
# repository policy. The three actions here are the ones a repository can authorise.
resource "aws_ecr_repository_policy" "cross_account_pull" {
  for_each = length(var.pull_account_ids) > 0 ? aws_ecr_repository.this : {}

  repository = each.value.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCrossAccountPull"
        Effect = "Allow"
        Principal = {
          AWS = [for id in var.pull_account_ids : "arn:aws:iam::${id}:root"]
        }
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
      },
    ]
  })
}
