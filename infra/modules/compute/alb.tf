# Application Load Balancer, TLS, and the Cognito authentication action.

locals {
  # Rules attach to whichever listener actually serves the application. Before TLS
  # that is port 80; after, port 443 (port 80 becomes a redirect and serves nothing).
  app_listener_arn = var.enable_tls ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn

  # ⚠️ Cognito requires HTTPS. The ALB will not attach an authenticate-cognito
  # action to an HTTP listener, so auth is only live once TLS is.
  cognito_active = var.enable_tls && var.enable_cognito
}

# Enabling Cognito without TLS silently produces an UNAUTHENTICATED deployment:
# the flag looks on, and nothing enforces it. Fail the plan instead.
resource "terraform_data" "auth_guard" {
  input = "${var.enable_tls}-${var.enable_cognito}"

  lifecycle {
    precondition {
      condition     = !var.enable_cognito || var.enable_tls
      error_message = "enable_cognito requires enable_tls: an ALB cannot attach authenticate-cognito to an HTTP listener, so the environment would come up with NO authentication while appearing configured."
    }
  }
}

resource "aws_lb" "this" {
  name               = var.name_prefix
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [var.alb_security_group_id]

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
# ⚠️ HEALTH CHECKS ARE UNAFFECTED BY LISTENER RULES, INCLUDING THE COGNITO ACTION.
#
# The load balancer probes each registered target DIRECTLY at its IP and port; the
# probe never traverses a listener, so it never meets the authentication action. If
# it did, every task would fail its check behind Cognito and no service could ever
# reach steady state. Verified by construction: health_check below configures the
# TARGET GROUP, while authenticate-cognito is an action on a LISTENER RULE — two
# different objects on two different paths.
# --------------------------------------------------------------------------- #

resource "aws_lb_target_group" "api" {
  name        = "${var.name_prefix}-api"
  port        = var.api_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

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
# Listeners
# --------------------------------------------------------------------------- #

# Port 80. Before TLS it serves the application; after, it does nothing but
# redirect. A 301 is permanent and cacheable, which is correct once the site is
# HTTPS-only — browsers stop attempting the cleartext request at all.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  dynamic "default_action" {
    for_each = var.enable_tls ? [1] : []

    content {
      type = "redirect"

      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }

  dynamic "default_action" {
    for_each = var.enable_tls ? [] : [1]

    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.frontend.arn
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-http" })
}

# Port 443 — PHASE 2 ONLY, and the only listener that can carry authentication.
resource "aws_lb_listener" "https" {
  count = var.enable_tls ? 1 : 0

  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn

  # TLS 1.3 with a 1.2 floor. TLS 1.3 removes the negotiated-cipher and
  # renegotiation classes of downgrade attack outright; keeping 1.2 available
  # avoids failing clients that cannot do 1.3, which for a browser-facing app in
  # 2026 is a small set but not empty. A 1.2-only policy would be weaker for no
  # gain; a 1.3-only policy would break those clients for little.
  ssl_policy = var.ssl_policy

  # ⚠️ THE DEFAULT ACTION IS WHERE AUTHENTICATION LIVES.
  #
  # It covers every request that matches no explicit rule. The explicit rules below
  # ALSO carry the action — see the comment there, which is the part that is easy
  # to get wrong.
  dynamic "default_action" {
    for_each = local.cognito_active ? [1] : []

    content {
      type  = "authenticate-cognito"
      order = 1

      authenticate_cognito {
        user_pool_arn       = aws_cognito_user_pool.this[0].arn
        user_pool_client_id = aws_cognito_user_pool_client.this[0].id
        user_pool_domain    = aws_cognito_user_pool_domain.this[0].domain

        # ⚠️ DELIBERATELY LONG — see the module README. A session that expires
        # mid-use turns an in-flight fetch() into a 302 toward a login page, which
        # browser JavaScript cannot follow; the application then fails in ways that
        # look like application bugs. A long session moves expiry to BETWEEN visits.
        session_timeout = var.cognito_session_timeout_seconds

        on_unauthenticated_request = "authenticate"
      }
    }
  }

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
    order            = local.cognito_active ? 2 : null
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-https" })
}

# --------------------------------------------------------------------------- #
# Listener rules
#
# ⚠️ THE SUBTLETY THAT DECIDES WHETHER THIS IS SECURE.
#
# An ALB evaluates rules in priority order and applies the FIRST match. The default
# action runs only when NOTHING matches. So a plain forward rule for /api/* does
# NOT inherit the listener's authenticate-cognito default — it BYPASSES it, leaving
# every API path, including document upload, open to the internet.
#
# Each rule below therefore carries the authentication action itself, ordered ahead
# of the forward. Removing it from any one rule silently opens that path.
# --------------------------------------------------------------------------- #

resource "aws_lb_listener_rule" "api" {
  listener_arn = local.app_listener_arn
  priority     = 100

  dynamic "action" {
    for_each = local.cognito_active ? [1] : []

    content {
      type  = "authenticate-cognito"
      order = 1

      authenticate_cognito {
        user_pool_arn              = aws_cognito_user_pool.this[0].arn
        user_pool_client_id        = aws_cognito_user_pool_client.this[0].id
        user_pool_domain           = aws_cognito_user_pool_domain.this[0].domain
        session_timeout            = var.cognito_session_timeout_seconds
        on_unauthenticated_request = "authenticate"
      }
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
    order            = local.cognito_active ? 2 : null
  }

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-api" })
}

# The health and docs endpoints are served at the APPLICATION ROOT — /health,
# /health/live, /health/ready — not under the /api/v1 prefix every feature router
# uses. Without this rule they fall through to the default action and reach the
# FRONTEND, which does not serve them.
#
# This rule being behind Cognito does NOT affect the target group health check,
# which probes targets directly and never traverses a listener.
resource "aws_lb_listener_rule" "api_root_paths" {
  listener_arn = local.app_listener_arn
  priority     = 90

  dynamic "action" {
    for_each = local.cognito_active ? [1] : []

    content {
      type  = "authenticate-cognito"
      order = 1

      authenticate_cognito {
        user_pool_arn              = aws_cognito_user_pool.this[0].arn
        user_pool_client_id        = aws_cognito_user_pool_client.this[0].id
        user_pool_domain           = aws_cognito_user_pool_domain.this[0].domain
        session_timeout            = var.cognito_session_timeout_seconds
        on_unauthenticated_request = "authenticate"
      }
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
    order            = local.cognito_active ? 2 : null
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
