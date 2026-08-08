# Documents bucket — uploaded borrower files.
#
# Created by Terraform here, unlike the lower environment's, which was made by
# hand and is deliberately unmanaged. This one holds real borrower NPI, so its
# controls are the point rather than a formality.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name

  # The bucket holds the only copy of every uploaded document. Losing it is not
  # recoverable from the database, which stores keys rather than content.
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

# SSE-KMS with the environment CMK, not SSE-S3. A CMK gives a separate audit trail
# and a revocation lever that the AWS-managed key does not: denying the key denies
# the data, independently of the bucket policy.
#
# bucket_key_enabled cuts KMS request cost substantially on read-heavy access by
# caching a bucket-level data key, without weakening the encryption.
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

# Deny any request that did not arrive over TLS. Bucket encryption protects data at
# rest; this is the in-transit half, and it is enforced rather than assumed.
data "aws_iam_policy_document" "tls_only" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.this.arn,
      "${aws_s3_bucket.this.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.this.id
  policy = data.aws_iam_policy_document.tls_only.json

  # The public access block must be in place before a policy is attached, or the
  # policy write can be rejected as potentially-public.
  depends_on = [aws_s3_bucket_public_access_block.this]
}

# ⚠️ THERE IS DELIBERATELY NO LIFECYCLE EXPIRY RULE.
#
# A disposal obligation exists in principle, but the retention period is an
# unresolved policy decision, not a technical default. Inventing a number here
# would silently become the answer — and a lifecycle rule deletes borrower records
# on a schedule nobody agreed to. Absence is the honest state until the decision is
# made. See the result doc, where it is recorded as an open item.
