output "zone_id" {
  description = "Hosted zone id — the environment needs it to create the alias record pointing at the load balancer."
  value       = aws_route53_zone.this.zone_id
}

output "zone_name" {
  description = "Hosted zone name."
  value       = aws_route53_zone.this.name
}

output "name_servers" {
  description = <<-EOT
    ⚠️ THE FOUR NAMESERVERS TO ENTER AT THE REGISTRAR.

    This is the output of phase 1 and the input to the manual delegation step. Until
    these are live for the subdomain, ACM cannot validate and phase 2 will fail.

    Read them with:  terraform output -json name_servers
    Verify with:     dig +short NS <domain>
  EOT
  value       = aws_route53_zone.this.name_servers
}

output "certificate_arn" {
  description = "Issued certificate ARN, or null in phase 1. Consumed by the HTTPS listener."
  value       = var.enable_tls ? aws_acm_certificate_validation.this[0].certificate_arn : null
}
