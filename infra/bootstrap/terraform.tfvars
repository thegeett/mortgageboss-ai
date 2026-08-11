# Bootstrap values. Non-secret: a region, an account id, and a bucket name.
# The account id lives here (a .tfvars file), never in a .tf file — see the
# ground rules in docs/tickets/C2-terraform.md.
#
# THE STAGING ACCOUNT. There is no tooling account to bootstrap — envs/dev is a
# reference template that is never applied, and production will bootstrap its own.

aws_region        = "us-east-1"
aws_account_id    = "058190633983"
state_bucket_name = "mbai-tfstate-058190633983"
