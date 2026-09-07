# Inbound borrower mail — SES receipt into S3, notified through SNS to SQS (INFRA-1).
#
# THE SHAPE. A borrower emails lf-<token>@<mail_domain>. SES accepts it, writes the raw message to
# S3 under a prefix, and publishes a notification; SNS fans that to SQS, which the worker polls. The
# raw `.eml` is the record of what arrived and is kept for the retention period; everything the
# application derives from it is reproducible, and the object is not.
#
# THIS DOMAIN SENDS NOTHING, and that is a control rather than an omission. No SPF, no DKIM, no A
# record, no MAIL FROM. An inbound MX overlapping an authenticated sending domain is the documented
# cause of an infinite mail loop — a bounce to a bouncing address, forever, against a borrower's
# mailbox. Outbound identity is INFRA-3's, on its own subdomains.
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
  # The prefix every stored message lands under. A prefix rather than the bucket root so a lifecycle
  # rule can be scoped to inbound mail alone, and so a future second producer cannot collide.
  object_prefix = "inbound/"

  rule_name = "${var.name_prefix}-inbound"

  # The SES source ARN both the bucket policy and the key policy condition on. It names the RULE,
  # not the service — so a different rule in the same account cannot write here.
  receipt_rule_arn = "arn:aws:ses:${var.aws_region}:${var.aws_account_id}:receipt-rule-set/${var.rule_set_name}:receipt-rule/${local.rule_name}"
}

# --------------------------------------------------------------------------- #
# Domain identity and DNS
# --------------------------------------------------------------------------- #
resource "aws_ses_domain_identity" "this" {
  domain = var.mail_domain
}

resource "aws_route53_record" "verification" {
  zone_id = var.route53_zone_id
  name    = "_amazonses.${var.mail_domain}"
  type    = "TXT"
  ttl     = 600
  records = [aws_ses_domain_identity.this.verification_token]
}

resource "aws_ses_domain_identity_verification" "this" {
  domain     = aws_ses_domain_identity.this.id
  depends_on = [aws_route53_record.verification]
}

# The MX that makes the domain receivable. `inbound-smtp.<region>` is the receipt endpoint, which is
# a DIFFERENT hostname from the sending endpoint and exists only in regions where SES email
# receiving is available.
resource "aws_route53_record" "mx" {
  zone_id = var.route53_zone_id
  name    = var.mail_domain
  type    = "MX"
  ttl     = 600
  records = ["10 inbound-smtp.${var.aws_region}.amazonaws.com"]
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

# Retention. Glacier first because a stored message is read once on arrival and then almost never;
# expiry because "keep everything forever" is itself a finding under the Safeguards Rule's disposal
# duty. A LEGAL HOLD MUST SUPPRESS THIS — that flag is LP-821's, and `phase4.md` §6 says it ships
# BEFORE the purge job. This rule IS the purge job, and it is created here on day one of the
# critical path, so the ordering matters: see the note in the module header of the ticket doc.
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "inbound-retention"
    status = "Enabled"

    filter {
      prefix = local.object_prefix
    }

    transition {
      days          = var.glacier_after_days
      storage_class = "GLACIER_IR"
    }

    expiration {
      days = var.retention_years * 365
    }

    # THIRTY DAYS WOULD HAVE BEEN THE EARLY PURGE, not the five-year one. The bucket is versioned,
    # so a DELETE does not remove anything: it writes a delete marker and makes the message's only
    # version noncurrent. At 30 days that version is destroyed permanently — five years before the
    # `expiration` rule above would have touched it, and with no legal hold able to intervene
    # because that flag is LP-821, in M5.
    #
    # `phase4.md` §6 says the legal-hold flag ships BEFORE the purge job. The five-year expiry does
    # not actually conflict with that, since nothing can reach five years before LP-821 lands. This
    # rule did. Noncurrent versions therefore keep the same retention as current ones until there is
    # something that can suppress a purge; SES writes a unique key per message, so overwrites are
    # rare and holding the versions costs close to nothing.
    noncurrent_version_expiration {
      noncurrent_days = var.retention_years * 365
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
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

resource "aws_ses_receipt_rule" "store" {
  name          = local.rule_name
  rule_set_name = aws_ses_receipt_rule_set.this.rule_set_name
  recipients    = [var.mail_domain]
  enabled       = true
  scan_enabled  = true
  tls_policy    = "Require"

  s3_action {
    bucket_name       = aws_s3_bucket.this.id
    object_key_prefix = local.object_prefix
    kms_key_arn       = var.kms_key_arn
    topic_arn         = aws_sns_topic.this.arn
    position          = 1
  }

  depends_on = [
    aws_s3_bucket_policy.this,
    aws_sns_topic_policy.this,
    aws_ses_domain_identity_verification.this,
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
