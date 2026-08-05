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
  # match. Untagged images are expired first (rule 1) so the "keep last N tagged"
  # count in rule 2 is not consumed by garbage.
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
        description  = "Keep only the last ${var.keep_last_images} tagged images."
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
