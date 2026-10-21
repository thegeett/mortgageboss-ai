# Inbound borrower mail — SES receipt into S3, notified through SNS to SQS (INFRA-1, LP-981).
#
# THE SHAPE. A borrower emails a loan file's address. SES accepts it, writes the raw message to S3
# under `inbound/`, and publishes a notification; SNS fans that to SQS, which the worker polls. The
# raw `.eml` is the record of what arrived and is kept (nothing here expires it); everything the
# application derives from it is reproducible, and the object is not.
#
# SHARED PLUMBING, NO DOMAIN (LP-981). This module owns no domain, identity or DNS record. Each
# receiving domain — `mail.<env domain>` and every customer subdomain — is an SES identity created
# elsewhere, with its MX pointed at SES. The one rule here has no recipient condition, so it accepts
# mail for all of them; the worker routes by envelope recipient.
#
# ONE BUCKET FOR ALL RAW MAIL. `inbound/` is written by SES; `outbound/` by the worker, a copy of
# each message it sends. SES may write only `inbound/`.
#
# ONE ACTIVE RULE SET PER ACCOUNT PER REGION. `aws_ses_active_receipt_rule_set` is therefore a
# whole-account switch, not a per-module resource: applying a second one deactivates the first and
# inbound mail stops with no error raised anywhere. The rule set is a VARIABLE so a second consumer
# adds a rule to this set rather than creating its own.

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
  # SES writes received mail under `object_prefix`; the worker writes sent mail under
  # `outbound_prefix`. Separate prefixes so SES's write grant can be limited to its own.
  object_prefix   = "inbound/"
  outbound_prefix = "outbound/"

  rule_name = "${var.name_prefix}-inbound"

  # The SES source ARN both the bucket policy and the key policy condition on. It names the RULE,
  # not the service — so a different rule in the same account cannot write here.
  receipt_rule_arn = "arn:aws:ses:${var.aws_region}:${var.aws_account_id}:receipt-rule-set/${var.rule_set_name}:receipt-rule/${local.rule_name}"
}

# --------------------------------------------------------------------------- #
# The bucket
# --------------------------------------------------------------------------- #
resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name

  # The raw message is the record of what a borrower actually sent. Everything derived from it can
  # be recomputed; it cannot.
  lifecycle {
    prevent_destroy = true
  }

  tags = merge(var.tags, { Name = var.bucket_name })
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

# Storage class only, identical for `inbound/` and `outbound/`: one rule per prefix rather than one
# unfiltered rule, so GuardDuty's bucket-root test object and anything else added later is not swept
# up in it. Glacier because a stored message is read once on arrival and then almost never.
#
# TRANSITION-ONLY, NO EXPIRATION OF EITHER KIND. v1 keeps every message (loan-email.md NFR-18). A
# legal hold is a flag in the database, and S3 lifecycle never reads the database: an `expiration`
# or `noncurrent_version_expiration` here would delete held correspondence on schedule, and there is
# nothing to stop it. Add expiry back only together with something that makes deletion respect a
# hold (S3 Object Lock legal holds, or a purge job that checks the flag).
#
# The bucket is versioned, so a DELETE only writes a delete marker; with no noncurrent expiry the
# version behind it stays until someone removes it by version id.
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  dynamic "rule" {
    for_each = {
      "inbound-retention"  = local.object_prefix
      "outbound-retention" = local.outbound_prefix
    }

    content {
      id     = rule.key
      status = "Enabled"

      filter {
        prefix = rule.value
      }

      transition {
        days          = var.glacier_after_days
        storage_class = "GLACIER_IR"
      }

      # Parts of an upload that never completed; never a stored message.
      abort_incomplete_multipart_upload {
        days_after_initiation = 7
      }
    }
  }
}

# SES's write permission, and the in-transit half.
#
# CONDITIONED ON SourceAccount + SourceArn, NOT ON `aws:Referer`. The referer form appears in most
# older examples and in a good deal of published Terraform; AWS's current documentation uses the
# source-account and source-ARN conditions, which name THIS receipt rule rather than the service at
# large. Verified against the SES developer guide's "Giving permissions to Amazon SES for email
# receiving" page on 2026-09-07 rather than written from memory.
data "aws_iam_policy_document" "bucket" {
  statement {
    sid    = "AllowSESPuts"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.this.arn}/${local.object_prefix}*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [local.receipt_rule_arn]
    }
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions   = ["s3:*"]
    resources = [aws_s3_bucket.this.arn, "${aws_s3_bucket.this.arn}/*"]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  bucket = aws_s3_bucket.this.id
  policy = data.aws_iam_policy_document.bucket.json

  # Without this the deny statement can be evaluated before the public access block exists.
  depends_on = [aws_s3_bucket_public_access_block.this]
}

# --------------------------------------------------------------------------- #
# Notification: SNS -> SQS
# --------------------------------------------------------------------------- #
resource "aws_sns_topic" "this" {
  name              = "${var.name_prefix}-inbound-mail"
  kms_master_key_id = var.kms_key_arn
  tags              = var.tags
}

data "aws_iam_policy_document" "topic" {
  statement {
    sid    = "AllowSESPublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.this.arn]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [local.receipt_rule_arn]
    }
  }
}

resource "aws_sns_topic_policy" "this" {
  arn    = aws_sns_topic.this.arn
  policy = data.aws_iam_policy_document.topic.json
}

# The DLQ exists so a message that cannot be processed stops being retried and starts being
# VISIBLE. Without one, a poison message is redelivered until it ages out and the only trace is a
# worker log nobody reads.
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name_prefix}-inbound-mail-dlq"
  message_retention_seconds = var.message_retention_seconds
  kms_master_key_id         = var.kms_key_arn
  tags                      = var.tags
}

resource "aws_sqs_queue" "this" {
  name                       = "${var.name_prefix}-inbound-mail"
  message_retention_seconds  = var.message_retention_seconds
  kms_master_key_id          = var.kms_key_arn
  visibility_timeout_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = var.tags
}

data "aws_iam_policy_document" "queue" {
  statement {
    sid    = "AllowSNSDeliver"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.this.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.this.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "this" {
  queue_url = aws_sqs_queue.this.id
  policy    = data.aws_iam_policy_document.queue.json
}

resource "aws_sns_topic_subscription" "queue" {
  topic_arn            = aws_sns_topic.this.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.this.arn
  raw_message_delivery = true
}

# --------------------------------------------------------------------------- #
# The receipt rule
# --------------------------------------------------------------------------- #
resource "aws_ses_receipt_rule_set" "this" {
  rule_set_name = var.rule_set_name
}

# No `recipients`: the rule matches every verified identity whose MX points at SES (LP-981).
#
# No `kms_key_arn` on the S3 action. Setting one switches SES to CLIENT-side encryption, which only
# an S3 encryption client can read. The bucket's default SSE-KMS encrypts the object instead, and
# the worker reads it with a plain `get_object`.
resource "aws_ses_receipt_rule" "store" {
  name          = local.rule_name
  rule_set_name = aws_ses_receipt_rule_set.this.rule_set_name
  enabled       = true
  scan_enabled  = true
  tls_policy    = "Require"

  s3_action {
    bucket_name       = aws_s3_bucket.this.id
    object_key_prefix = local.object_prefix
    topic_arn         = aws_sns_topic.this.arn
    position          = 1
  }

  depends_on = [
    aws_s3_bucket_policy.this,
    aws_sns_topic_policy.this,
  ]
}

# The one claim in this module nothing else can check.
#
# `local.receipt_rule_arn` is BUILT BY HAND, and it has to be: SES validates permissions when the
# receipt rule is created, so the bucket and key policies must already grant access — which means
# they cannot reference `aws_ses_receipt_rule.store.arn`, because it does not exist yet. Terraform's
# graph therefore never compares the string in those two Condition blocks against the rule it names.
#
# A wrong ARN here does NOT fail at apply. Every resource applies cleanly, SES accepts the message,
# the S3 write is denied on a condition that matches nothing, and the mail is gone with the sender
# seeing success. That is the exact failure this module's permission work exists to prevent, reached
# by a typo instead of by a missing grant.
#
# The check runs on every plan AFTER the first apply, when the real ARN is in state, and reports a
# warning rather than blocking — the resources are already correct or already wrong by then, and a
# hard failure would only stop the plan that tells you.
check "receipt_rule_arn_matches_the_policies" {
  assert {
    condition     = aws_ses_receipt_rule.store.arn == local.receipt_rule_arn
    error_message = <<-EOT
      The receipt-rule ARN granted in the S3 bucket policy and the KMS key policy does not match the
      rule that was actually created.

        granted: ${local.receipt_rule_arn}
        actual:  ${aws_ses_receipt_rule.store.arn}

      SES will accept inbound mail and then fail to write it to the bucket, with the sender seeing
      a successful delivery. Fix `local.receipt_rule_arn` in this module.
    EOT
  }
}

# NOT CREATED HERE, DELIBERATELY: `aws_ses_active_receipt_rule_set`. Activation is an ACCOUNT-WIDE,
# single-valued switch — applying one deactivates whatever was active, silently, and inbound mail
# stops with no error surfaced anywhere. It is a human step, taken once, with the account's other
# SES receipt usage in view. See the ticket doc.
