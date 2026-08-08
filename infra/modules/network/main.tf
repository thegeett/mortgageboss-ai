# Network — VPC, subnets across two AZs, egress (NAT or interface endpoints),
# and the four security groups.
#
# Environment-agnostic by construction: every name derives from var.name_prefix,
# the region arrives as a variable and is only ever interpolated, and AZ names
# come from var.availability_zones. There is no literal environment name,
# account id, or region anywhere in this file.

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
  # Universal facts, not environment settings — these are the ports the
  # application listens on and the engines' well-known ports.
  api_port      = 8000
  frontend_port = 3000
  postgres_port = 5432
  redis_port    = 6379

  az_count = length(var.availability_zones)

  # /16 VPC carved into /20s: public subnets first, then private. newbits = 4.
  public_subnet_cidrs  = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, 4, i)]
  private_subnet_cidrs = [for i in range(local.az_count) : cidrsubnet(var.vpc_cidr, 4, i + local.az_count)]

  # AZs that get interface endpoints. Empty (the default) means every AZ — the
  # redundant, more expensive placement. A subset is the single-AZ cost choice.
  endpoint_azs = length(var.endpoint_availability_zones) > 0 ? var.endpoint_availability_zones : var.availability_zones

  endpoint_subnet_ids = [
    for i, az in var.availability_zones : aws_subnet.private[i].id
    if contains(local.endpoint_azs, az)
  ]
}

# Private tasks need SOME route to ECR, Logs, Secrets Manager and Bedrock. With
# neither NAT nor endpoints they cannot even pull their image, and the failure
# appears at first deploy as an opaque ECS task-placement error. Catch it here.
resource "terraform_data" "egress_guard" {
  input = "${var.enable_nat_gateway}-${var.enable_vpc_endpoints}"

  lifecycle {
    precondition {
      condition     = var.enable_nat_gateway || var.enable_vpc_endpoints
      error_message = "Private subnets would have no egress path: enable_nat_gateway and enable_vpc_endpoints are both false. Tasks could not pull images from ECR. Enable one."
    }
  }
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(var.tags, { Name = var.name_prefix })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, { Name = var.name_prefix })
}

resource "aws_subnet" "public" {
  count = local.az_count

  vpc_id                  = aws_vpc.this.id
  cidr_block              = local.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-${var.availability_zones[count.index]}"
    Tier = "public"
  })
}

resource "aws_subnet" "private" {
  count = local.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-${var.availability_zones[count.index]}"
    Tier = "private"
  })
}

# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-public" })
}

resource "aws_route_table_association" "public" {
  count = local.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ONE NAT gateway, not one per AZ. A per-AZ NAT is the availability-correct
# choice (an AZ outage takes its NAT with it) but triples the cost for an
# environment with a single-AZ database — the database is already the AZ-failure
# bound, so a second NAT would buy nothing.
resource "aws_eip" "nat" {
  count = var.enable_nat_gateway ? 1 : 0

  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.name_prefix}-nat" })
}

resource "aws_nat_gateway" "this" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = merge(var.tags, { Name = "${var.name_prefix}-nat" })

  depends_on = [aws_internet_gateway.this]
}

# One private route table per AZ. Even with a single shared NAT this keeps the
# per-AZ structure, so adding a second NAT later is a change to routes rather
# than a re-architecture.
resource "aws_route_table" "private" {
  count = local.az_count

  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-${var.availability_zones[count.index]}"
  })
}

resource "aws_route" "private_nat" {
  count = var.enable_nat_gateway ? local.az_count : 0

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}

resource "aws_route_table_association" "private" {
  count = local.az_count

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# --------------------------------------------------------------------------- #
# Security groups — referenced by ID, never by CIDR.
#
# No group below permits 0.0.0.0/0 on the database or cache ports. The only
# 0.0.0.0/0 ingress in this module is 80/443 on the load balancer, which is the
# point of a load balancer.
# --------------------------------------------------------------------------- #

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Load balancer: public HTTP/HTTPS in, application ports out."
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-alb" })
}

# One rule per (port, CIDR). An empty allowlist yields the usual public pair.
locals {
  alb_ingress_cidrs = length(var.alb_ingress_cidr_blocks) > 0 ? var.alb_ingress_cidr_blocks : ["0.0.0.0/0"]

  alb_ingress_rules = merge([
    for port in [80, 443] : {
      for cidr in local.alb_ingress_cidrs :
      "${port}-${cidr}" => { port = port, cidr = cidr }
    }
  ]...)
}

resource "aws_vpc_security_group_ingress_rule" "alb" {
  for_each = local.alb_ingress_rules

  security_group_id = aws_security_group.alb.id
  description       = "Port ${each.value.port} from ${each.value.cidr}."
  cidr_ipv4         = each.value.cidr
  from_port         = each.value.port
  to_port           = each.value.port
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_all" {
  security_group_id = aws_security_group.alb.id
  description       = "Unrestricted egress to reach task targets."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.name_prefix}-ecs-tasks"
  description = "ECS tasks: application ports from the load balancer only."
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-ecs-tasks" })
}

resource "aws_vpc_security_group_ingress_rule" "tasks_api" {
  security_group_id            = aws_security_group.ecs_tasks.id
  description                  = "API port from the load balancer only."
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = local.api_port
  to_port                      = local.api_port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "tasks_frontend" {
  security_group_id            = aws_security_group.ecs_tasks.id
  description                  = "Frontend port from the load balancer only."
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = local.frontend_port
  to_port                      = local.frontend_port
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "tasks_all" {
  security_group_id = aws_security_group.ecs_tasks.id
  description       = "Egress to AWS services via NAT or interface endpoints."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "rds" {
  name        = "${var.name_prefix}-rds"
  description = "PostgreSQL: from ECS tasks only. Never publicly reachable."
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-rds" })
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_tasks" {
  security_group_id            = aws_security_group.rds.id
  description                  = "PostgreSQL from ECS tasks only."
  referenced_security_group_id = aws_security_group.ecs_tasks.id
  from_port                    = local.postgres_port
  to_port                      = local.postgres_port
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "redis" {
  name        = "${var.name_prefix}-redis"
  description = "Redis: from ECS tasks only. Never publicly reachable."
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-redis" })
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_tasks" {
  security_group_id            = aws_security_group.redis.id
  description                  = "Redis from ECS tasks only."
  referenced_security_group_id = aws_security_group.ecs_tasks.id
  from_port                    = local.redis_port
  to_port                      = local.redis_port
  ip_protocol                  = "tcp"
}

# Interface endpoints need 443 from the tasks that use them.
resource "aws_security_group" "vpc_endpoints" {
  count = var.enable_vpc_endpoints ? 1 : 0

  name        = "${var.name_prefix}-vpce"
  description = "VPC interface endpoints: HTTPS from ECS tasks only."
  vpc_id      = aws_vpc.this.id

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpce" })
}

resource "aws_vpc_security_group_ingress_rule" "vpce_https" {
  count = var.enable_vpc_endpoints ? 1 : 0

  security_group_id            = aws_security_group.vpc_endpoints[0].id
  description                  = "HTTPS from ECS tasks."
  referenced_security_group_id = aws_security_group.ecs_tasks.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

# --------------------------------------------------------------------------- #
# VPC endpoints
#
# Service names are built from var.aws_region so this module stays region-free.
# The S3 gateway endpoint is separate: it is FREE, attaches to route tables
# rather than subnets, and is created whenever endpoints are enabled because ECR
# stores image LAYERS in S3 — an ECR interface endpoint without it cannot pull.
# --------------------------------------------------------------------------- #

# Interface endpoints are ENIs, billed PER ENDPOINT PER AZ. Placing them in a
# subset of AZs is the single biggest lever on their cost: five endpoints across
# two AZs is roughly double the same five in one.
#
# ⚠️ TASKS AND ENDPOINTS MUST MOVE TOGETHER. A task in an AZ with no local endpoint
# still works — private DNS resolves VPC-wide — but every call crosses an AZ
# boundary, which costs transfer and quietly gives back the AZ independence the
# placement was supposed to buy. Whatever AZs are listed here, put the tasks in the
# same ones.
resource "aws_vpc_endpoint" "interface" {
  for_each = var.enable_vpc_endpoints ? toset(var.interface_endpoint_services) : toset([])

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnet_ids
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-${replace(each.value, ".", "-")}" })
}

resource "aws_vpc_endpoint" "s3" {
  count = var.enable_vpc_endpoints ? 1 : 0

  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id

  tags = merge(var.tags, { Name = "${var.name_prefix}-s3" })
}
