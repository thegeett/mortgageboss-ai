variable "name_prefix" {
  description = "Dash-delimited resource name prefix, e.g. mbai-staging."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
  default     = {}
}

variable "send_domain" {
  description = <<-EOT
    The domain messages are sent FROM, e.g. mail.staging.mortgageboss.ai.

    Its own subdomain, separate from both the apex and from the inbound `inbox.` domain. An outbound
    identity overlapping an inbound MX is the documented cause of an infinite mail loop, and a
    reputation problem on transactional mail must not reach the apex.
  EOT
  type        = string
}

variable "bounce_domain" {
  description = <<-EOT
    The custom MAIL FROM domain — the envelope sender, where bounces are returned.

    AWS's requirements, quoted: the MAIL FROM domain "has to be a subdomain of the parent domain of
    a verified identity", "shouldn't be a subdomain that you also use to send email from", and
    "shouldn't be a subdomain that you use to receive email". `bounces.<parent>` satisfies all three
    against a `mail.<parent>` identity.
  EOT
  type        = string
}

variable "route53_zone_id" {
  description = "The hosted zone every record below is written into."
  type        = string
}

variable "aws_region" {
  description = "Region of the SES sending identity. The MAIL FROM MX names it."
  type        = string
}

variable "dmarc_report_address" {
  description = <<-EOT
    Where DMARC aggregate reports are sent (`rua=`). Required — a `p=none` policy with no reporting
    address is the one configuration that does nothing at all: it neither enforces nor informs.
  EOT
  type        = string
}

variable "dkim_signing_hosted_zone" {
  description = <<-EOT
    The hosted-zone suffix each DKIM CNAME points at, WITHOUT the token.

    A VARIABLE, AND THIS IS THE INTERESTING PART. The SES guide says each CNAME's value is "the DKIM
    token followed by a hosted zone domain (for example, `token.dkim.amazonses.com` or
    `token.a31d.dkim.us-west-2.amazonses.com`)" and that "the hosted zone portion VARIES BY AWS
    REGION AND CELL". The authoritative value is the `SigningHostedZone` field in `GetEmailIdentity`'s
    `DkimAttributes`.

    The Terraform provider does not expose it — `aws_ses_domain_dkim` returns only `dkim_tokens`, and
    `aws_sesv2_email_identity.dkim_signing_attributes` returns only `tokens` (checked against the
    provider's own schema, aws 5.100.0). So Terraform cannot construct the correct value on its own,
    and hardcoding the common form would be right in most cells and silently wrong in the rest.

    Default is the common form. If DKIM does not verify after apply, read `SigningHostedZone` from
    `aws sesv2 get-email-identity --email-identity <send_domain>` and set this.
  EOT
  type        = string
  default     = "dkim.amazonses.com"
}

variable "behavior_on_mx_failure" {
  description = <<-EOT
    What SES does when the MAIL FROM MX is missing or wrong.

    `RejectMessage`, not `UseDefaultValue`. The fallback silently reverts the envelope sender to an
    `amazonses.com` subdomain — mail still goes out, SPF still passes, and the bounce path we built
    is simply not used, with nothing anywhere saying so. Bounces then land somewhere LP-819 cannot
    read, which is the failure that ticket exists to prevent. Refusing to send is louder and cheaper.
  EOT
  type        = string
  default     = "RejectMessage"
}
