# Application Load Balancer — HTTP :80 only. C4 adds HTTPS and the custom domain.

resource "aws_lb" "this" {
  name               = var.name_prefix
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [var.alb_security_group_id]

  # Deliberately off by default: dropping invalid headers is desirable, but turning
  # it on silently changes which requests reach the app, so it is an explicit choice.
  drop_invalid_header_fields = true

  dynamic "access_logs" {
    for_each = var.enable_alb_access_logs ? [1] : []

    content {
      bucket  = var.alb_access_logs_bucket
      prefix  = var.name_prefix
      enabled = true
    }
  }

  tags = merge(var.tags, { Name = var.name_prefix })
}

# --------------------------------------------------------------------------- #
# Target groups — target_type "ip" is REQUIRED for Fargate.
#
# awsvpc gives every task its own ENI, so there is no instance to register; an
# "instance" target group cannot express a Fargate task at all.
# --------------------------------------------------------------------------- #

resource "aws_lb_target_group" "api" {
  name        = "${var.name_prefix}-api"
  port        = var.api_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  # 300s (the AWS default) makes every deploy crawl for no benefit — these are
  # short HTTP requests, not long-lived connections.
  deregistration_delay = var.deregistration_delay_seconds

  health_check {
    enabled             = true
    path                = var.health_check_path
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-api" })

  # The listener rules below reference this group; replacing it in place would
  # break them mid-apply.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_target_group" "frontend" {
  name        = "${var.name_prefix}-frontend"
  port        = var.frontend_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  deregistration_delay = var.deregistration_delay_seconds

  # The frontend has no dedicated health endpoint, so its own root path is the
  # check. Next.js serves it without touching the API, so this stays honest about
  # "is the frontend up" rather than transitively testing the backend.
  health_check {
    enabled             = true
    path                = "/"
    protocol            = "HTTP"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-frontend" })

  lifecycle {
    create_before_destroy = true
  }
}

# --------------------------------------------------------------------------- #
# Listener — default to the frontend, with explicit rules routing to the API.
# --------------------------------------------------------------------------- #

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-http" })
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-api" })
}

# ⚠️ SEPARATE RULE, and it is not optional.
#
# The health endpoints are served at the APPLICATION ROOT — /health, /health/live,
# /health/ready (verified in backend/app/main.py) — NOT under the /api/v1 prefix
# that every feature router uses. Without this rule they fall through to the
# default action and reach the FRONTEND, which does not serve them.
#
# The docs path is included for the same reason: FastAPI mounts /docs, /redoc and
# /openapi.json at the root, so they would otherwise 404 against the frontend.
resource "aws_lb_listener_rule" "api_root_paths" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 90

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = [
        "/health",
        "/health/*",
        "/docs",
        "/docs/*",
        "/redoc",
        "/openapi.json",
      ]
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-api-root" })
}
