# Network module inputs.
#
# NOTHING environment-specific has a default. A default here is how a staging
# value silently inherits a lower environment's setting. The only defaults
# permitted are genuinely universal facts (port numbers), which live in main.tf
# as locals rather than as overridable variables.

variable "name_prefix" {
  description = "Prefix for every resource name. Every name in this module derives from it."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this module."
  type        = map(string)
}

variable "aws_region" {
  description = "Region, used only to build VPC endpoint service names. Never hardcoded in this module."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR for the VPC. Environments that may ever peer MUST NOT share a CIDR."
  type        = string
}

variable "availability_zones" {
  description = "AZ names to spread subnets across. Two minimum — RDS subnet groups require two even for a single-instance database."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "At least two availability zones are required (RDS subnet groups mandate it)."
  }
}

variable "enable_nat_gateway" {
  description = <<-EOT
    Route private-subnet egress through a NAT gateway.

    Mutually exclusive in practice with enable_vpc_endpoints: private tasks need
    ONE of the two to reach ECR, CloudWatch Logs, Secrets Manager and Bedrock. If
    both are false the tasks cannot start (they cannot pull an image), which the
    precondition in main.tf catches at plan time rather than at first deploy.

    See docs/tickets/C2-terraform-result.md for the cost arithmetic.
  EOT
  type        = bool
}

variable "enable_vpc_endpoints" {
  description = <<-EOT
    Create VPC interface endpoints for ECR, CloudWatch Logs, Secrets Manager and
    the Bedrock runtime, plus the (free) S3 gateway endpoint.

    Keeps all task egress inside the AWS network — traffic never touches the
    public internet. That is a compliance property, not only a cost one.
  EOT
  type        = bool
}

variable "interface_endpoint_services" {
  description = <<-EOT
    Short service names for interface endpoints, e.g. "ecr.api". The full service
    name is built as com.amazonaws.<region>.<short name>, so this module never
    contains a literal region.

    Supplied by the environment rather than hardcoded here so that a deployment
    which does not use Bedrock is not forced to create a Bedrock endpoint.
  EOT
  type        = list(string)
}
