# DNS — a delegated Route 53 hosted zone and the ACM certificate for it.
#
# ⚠️ THIS MODULE DELIBERATELY KNOWS NOTHING ABOUT THE LOAD BALANCER.
#
# The alias A record that points the zone apex at the ALB is created by the
# ENVIRONMENT, not here. That is not an oversight — it is what keeps the module
# graph acyclic:
#
#     compute  needs  certificate_arn   (for the HTTPS listener)
#     dns      needs  alb_dns_name      (for the alias record)
#
# Both in one module is a cycle Terraform cannot resolve. Splitting the alias
# record out leaves a clean order: dns -> compute -> alias record.
#
# The zone is a DELEGATED SUBDOMAIN. The apex domain stays with its existing
# registrar and is never delegated to AWS — only the subdomain's NS records are.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

resource "aws_route53_zone" "this" {
  name    = var.domain_name
  comment = "${var.name_prefix} — delegated subdomain. NS records must be entered at the registrar."

  tags = merge(var.tags, { Name = var.domain_name })
}

# --------------------------------------------------------------------------- #
# ACM — PHASE 2 ONLY.
#
# Gated on enable_tls because DNS validation cannot succeed until the zone's NS
# records are live at the registrar, and that is a MANUAL step between the two
# applies. Attempting this before delegation propagates leaves the certificate in
# PENDING_VALIDATION while Terraform blocks until its timeout, then fails — no
# damage, but a slow and confusing first encounter.
# --------------------------------------------------------------------------- #

resource "aws_acm_certificate" "this" {
  count = var.enable_tls ? 1 : 0

  domain_name       = var.domain_name
  validation_method = "DNS"

  # The certificate is referenced by a live listener; replacing it in place would
  # break TLS mid-apply.
  lifecycle {
    create_before_destroy = true
  }

  tags = merge(var.tags, { Name = var.domain_name })
}

# One record per required validation domain. Written into the zone this module
# owns, so validation is automatic once delegation is live.
resource "aws_route53_record" "validation" {
  for_each = var.enable_tls ? {
    for o in aws_acm_certificate.this[0].domain_validation_options :
    o.domain_name => {
      name   = o.resource_record_name
      type   = o.resource_record_type
      record = o.resource_record_value
    }
  } : {}

  zone_id = aws_route53_zone.this.zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60

  # ACM may reissue with the same validation name; overwrite rather than fail.
  allow_overwrite = true
}

# Blocks until ACM reports ISSUED, so the HTTPS listener never references a
# certificate that cannot serve traffic.
resource "aws_acm_certificate_validation" "this" {
  count = var.enable_tls ? 1 : 0

  certificate_arn         = aws_acm_certificate.this[0].arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]

  timeouts {
    create = var.certificate_validation_timeout
  }
}
