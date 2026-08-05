# Bootstrap values. Non-secret: a region, an account id, and two resource names.
# The account id lives here (a .tfvars file), never in a .tf file — see the
# ground rules in docs/tickets/C2-terraform.md.

aws_region        = "us-east-1"
aws_account_id    = "591554480818"
state_bucket_name = "mbai-tfstate-591554480818"
lock_table_name   = "mbai-tf-locks"
