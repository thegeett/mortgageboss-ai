output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "VPC CIDR block."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet ids (load balancer)."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet ids (ECS tasks, RDS, ElastiCache)."
  value       = aws_subnet.private[*].id
}

output "alb_security_group_id" {
  description = "Security group for the load balancer."
  value       = aws_security_group.alb.id
}

output "ecs_tasks_security_group_id" {
  description = "Security group for ECS tasks."
  value       = aws_security_group.ecs_tasks.id
}

output "rds_security_group_id" {
  description = "Security group for the database."
  value       = aws_security_group.rds.id
}

output "redis_security_group_id" {
  description = "Security group for the cache."
  value       = aws_security_group.redis.id
}

output "nat_gateway_id" {
  description = "NAT gateway id, or null when egress goes via interface endpoints."
  value       = var.enable_nat_gateway ? aws_nat_gateway.this[0].id : null
}

output "interface_endpoint_ids" {
  description = "Map of short service name to interface endpoint id."
  value       = { for k, v in aws_vpc_endpoint.interface : k => v.id }
}

output "private_subnet_ids_by_az" {
  description = <<-EOT
    Map of AZ name to its private subnet id.

    Lets an environment pin ECS tasks to exactly the AZs that received interface
    endpoints — see endpoint_availability_zones.
  EOT
  value       = { for i, az in var.availability_zones : az => aws_subnet.private[i].id }
}

output "endpoint_subnet_ids" {
  description = "Private subnets that actually received interface endpoints."
  value       = local.endpoint_subnet_ids
}
