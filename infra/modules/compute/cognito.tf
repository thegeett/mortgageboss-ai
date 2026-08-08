# Cognito — an authentication layer at the LOAD BALANCER, in front of the app.
#
# The application already has its own JWT auth. This is deliberately a second,
# independent layer: an environment holding real borrower files should not be
# openly reachable, and an environment is exactly where an application auth bug
# would first appear. Enforcing at the ALB means an unauthenticated request never
# reaches a task at all — the application's own auth is not the only thing standing
# between the internet and borrower NPI.
#
# ⚠️ NO CIRCULAR DEPENDENCY, by construction. The callback URL is built from the
# DOMAIN NAME (a variable, known before anything is created), not from the ALB's
# generated DNS name. Deriving it from the ALB would make Cognito depend on the
# load balancer while the listener depends on Cognito — a cycle Terraform cannot
# resolve.

resource "aws_cognito_user_pool" "this" {
  count = var.enable_cognito ? 1 : 0

  name = var.name_prefix

  # ADMIN-CREATED USERS ONLY. Two people do not need self-signup, and an open
  # registration path on an environment holding borrower data is a way in.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # MFA. Optional here because enforcing it before any user exists locks out the
  # first admin-created account; recommended ON once users are created.
  mfa_configuration = var.cognito_mfa_configuration

  dynamic "software_token_mfa_configuration" {
    for_each = var.cognito_mfa_configuration == "OFF" ? [] : [1]

    content {
      enabled = true
    }
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  # Recovery by email only — no SMS, which is both weaker and an extra cost and
  # permission surface.
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = merge(var.tags, { Name = var.name_prefix })
}

resource "aws_cognito_user_pool_domain" "this" {
  count = var.enable_cognito ? 1 : 0

  # A Cognito-hosted prefix, globally unique across AWS — hence a variable rather
  # than a derivation, so a collision can be resolved without renaming resources.
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.this[0].id
}

resource "aws_cognito_user_pool_client" "this" {
  count = var.enable_cognito ? 1 : 0

  name         = var.name_prefix
  user_pool_id = aws_cognito_user_pool.this[0].id

  # The ALB exchanges an authorization code for tokens server-side, so it needs a
  # client secret. This is a confidential client, not a public one.
  generate_secret = true

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  # The fixed path the ALB serves for the OAuth callback. Built from the domain,
  # never from the ALB's own DNS name — see the module header.
  callback_urls = ["https://${var.domain_name}/oauth2/idpresponse"]
  logout_urls   = ["https://${var.domain_name}"]

  supported_identity_providers = ["COGNITO"]

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Refresh token lifetime must exceed the ALB session timeout, or the ALB cannot
  # silently renew and the user is bounced to the login page mid-session — the
  # exact failure the long session_timeout exists to avoid.
  refresh_token_validity = var.cognito_refresh_token_validity_days
  access_token_validity  = 60
  id_token_validity      = 60

  token_validity_units {
    refresh_token = "days"
    access_token  = "minutes"
    id_token      = "minutes"
  }
}
