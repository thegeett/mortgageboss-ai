# Outbound sending identity and the bounce path (INFRA-3).
#
# THREE SUBDOMAINS, THREE JOBS, AND THEY MUST NOT OVERLAP:
#
#   inbox.<parent>    receives borrower mail. MX to SES receipt. No SPF, no DKIM. (INFRA-1)
#   mail.<parent>     sends. SES identity, DKIM, DMARC. The `From:` domain.       (here)
#   bounces.<parent>  the envelope sender. MX to SES feedback, SPF.               (here)
#
# The separation is not tidiness. An outbound identity overlapping an inbound MX is the documented
# cause of an infinite mail loop, and AWS states outright that a MAIL FROM domain "shouldn't be a
# subdomain that you also use to send email from" or "that you use to receive email".
#
# DMARC ALIGNMENT, which is the reason `mail.` and `bounces.` are siblings rather than nested. For
# SPF to satisfy DMARC, the `From:` domain must align with the MAIL FROM domain — and under RELAXED
# alignment (SES's default, and ours: no `aspf=s` below) two subdomains of one organisational domain
# align. For DKIM, SES signs as the identity, which IS the `From:` domain, so DKIM aligns strictly.
# Either passing is enough; both passing is the point of doing both.
#
# Read from the SES developer guide's "Using a custom MAIL FROM domain", "Complying with DMARC
# authentication protocol in Amazon SES", and "Creating and verifying identities in Amazon SES" on
# 2026-09-07, headings verified on each page.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# --------------------------------------------------------------------------- #
# The sending identity
# --------------------------------------------------------------------------- #
resource "aws_ses_domain_identity" "send" {
  domain = var.send_domain
}

resource "aws_route53_record" "send_verification" {
  zone_id = var.route53_zone_id
  name    = "_amazonses.${var.send_domain}"
  type    = "TXT"
  ttl     = 600
  records = [aws_ses_domain_identity.send.verification_token]
}

resource "aws_ses_domain_dkim" "send" {
  domain = aws_ses_domain_identity.send.domain
}

# Three CNAMEs, one per token. The VALUE's suffix is a variable rather than a literal — see
# `dkim_signing_hosted_zone`. Terraform cannot read the authoritative value from the API through this
# provider, so it is an input with a default rather than a computed attribute pretending to be one.
resource "aws_route53_record" "dkim" {
  count = 3

  zone_id = var.route53_zone_id
  name    = "${aws_ses_domain_dkim.send.dkim_tokens[count.index]}._domainkey.${var.send_domain}"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_ses_domain_dkim.send.dkim_tokens[count.index]}.${var.dkim_signing_hosted_zone}"]
}

resource "aws_ses_domain_identity_verification" "send" {
  domain     = aws_ses_domain_identity.send.id
  depends_on = [aws_route53_record.send_verification]
}

# --------------------------------------------------------------------------- #
# The bounce path — a custom MAIL FROM domain
# --------------------------------------------------------------------------- #
resource "aws_ses_domain_mail_from" "send" {
  domain                 = aws_ses_domain_identity.send.domain
  mail_from_domain       = var.bounce_domain
  behavior_on_mx_failure = var.behavior_on_mx_failure
}

# EXACTLY ONE MX. AWS: "you must publish exactly one MX record to the DNS server of your MAIL FROM
# domain. If the MAIL FROM domain has multiple MX records, the custom MAIL FROM setup with Amazon SES
# will fail." That single record is what makes bounces reach SES — this domain cannot also be an
# inbound receipt domain, which is why LP-819 cannot "ingest the bounces subdomain" as mail. See the
# escalation in the ticket doc.
resource "aws_route53_record" "bounce_mx" {
  zone_id = var.route53_zone_id
  name    = var.bounce_domain
  type    = "MX"
  ttl     = 600
  records = ["10 feedback-smtp.${var.aws_region}.amazonses.com"]
}

resource "aws_route53_record" "bounce_spf" {
  zone_id = var.route53_zone_id
  name    = var.bounce_domain
  type    = "TXT"
  ttl     = 600
  records = ["v=spf1 include:amazonses.com ~all"]
}

# --------------------------------------------------------------------------- #
# DMARC
# --------------------------------------------------------------------------- #
# p=none, which is monitoring mode and is where AWS's own rollout guidance starts: "Start with a
# simple monitoring-mode record ... that requests that mail receiving organizations send you
# statistics". Tightening to quarantine and then reject is a later, evidence-led step, and doing it
# early is how legitimate mail stops being delivered.
#
# NO `aspf` OR `adkim` TAG, deliberately. Their absence means RELAXED alignment, which is what lets
# `From: @mail.<parent>` align with `MAIL FROM: @bounces.<parent>`. Adding `aspf=s` would break SPF
# alignment for this exact configuration — AWS says so directly: "In order to achieve SPF alignment
# with SES, the domain's DMARC policy must not specify a strict SPF policy (aspf=s)."
resource "aws_route53_record" "dmarc" {
  zone_id = var.route53_zone_id
  name    = "_dmarc.${var.send_domain}"
  type    = "TXT"
  ttl     = 600
  records = ["v=DMARC1; p=none; rua=mailto:${var.dmarc_report_address}"]
}

# --------------------------------------------------------------------------- #
# Where delivery events go
# --------------------------------------------------------------------------- #
# A CONFIGURATION SET WITH AN SNS DESTINATION, because a sending identity with nowhere to publish
# bounces drops them silently. LP-819 is the ticket that reads them; without this it would have
# nothing to read, and "no bounces" and "bounces going nowhere" look identical.
#
# `reject`, `bounce`, `complaint` and `delivery` only. Open and click tracking are not enabled: they
# require SES to rewrite links in the message body, which for a borrower document request means
# rewriting a secure upload link, and neither the tracking nor the rewrite is something this product
# has asked for.
resource "aws_sns_topic" "events" {
  name = "${var.name_prefix}-outbound-mail-events"
  tags = var.tags
}

resource "aws_ses_configuration_set" "this" {
  name = "${var.name_prefix}-outbound"

  delivery_options {
    tls_policy = "Require"
  }

  reputation_metrics_enabled = true
}

resource "aws_ses_event_destination" "sns" {
  name                   = "delivery-events"
  configuration_set_name = aws_ses_configuration_set.this.name
  enabled                = true
  matching_types         = ["reject", "bounce", "complaint", "delivery", "renderingFailure"]

  sns_destination {
    topic_arn = aws_sns_topic.events.arn
  }
}

data "aws_iam_policy_document" "events_topic" {
  statement {
    sid    = "AllowSESPublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ses.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.events.arn]
  }
}

resource "aws_sns_topic_policy" "events" {
  arn    = aws_sns_topic.events.arn
  policy = data.aws_iam_policy_document.events_topic.json
}
