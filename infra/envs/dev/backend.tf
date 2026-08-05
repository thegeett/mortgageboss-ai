# State backend — the bucket and lock table created by ../../bootstrap.
#
# Not reachable until bootstrap has been applied. Until then, work in this
# directory with `terraform init -backend=false` (validate only; a plan needs
# the backend).
#
# Values are literal because a backend block cannot use variables or locals —
# Terraform evaluates it before the variable graph exists. This is the one place
# in the environment where that is unavoidable.

terraform {
  backend "s3" {
    bucket         = "mbai-tfstate-591554480818"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mbai-tf-locks"
    encrypt        = true
  }
}
