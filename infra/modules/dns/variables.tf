variable "name_prefix" {
  description = "Prefix used in resource comments and tags."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "domain_name" {
  description = <<-EOT
    Fully-qualified name for the delegated zone, e.g. "sub.example.com".

    A SUBDOMAIN. The apex stays with the existing registrar; only this subdomain's
    NS records are entered there.
  EOT
  type        = string
}

variable "enable_tls" {
  description = <<-EOT
    Create the ACM certificate and its DNS validation records.

    ⚠️ PHASE GATE. false for the first apply, which creates only the zone and emits
    its nameservers; true for the second, after those nameservers have been entered
    at the registrar and propagated.

    Flipping this too early is not destructive — ACM simply sits in
    PENDING_VALIDATION until the validation timeout expires and the apply fails.
  EOT
  type        = bool
}

variable "certificate_validation_timeout" {
  description = <<-EOT
    How long to wait for ACM to report ISSUED.

    Validation is usually minutes once delegation is live. A longer timeout does
    not make it succeed sooner — it only changes how long a MISSING delegation
    takes to surface as a failure.
  EOT
  type        = string
  default     = "45m"
}
