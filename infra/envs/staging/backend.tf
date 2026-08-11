# State backend — the bucket created by ../../bootstrap.
#
# The bucket lives in the SAME ACCOUNT as the resources it describes. State records
# every resource in the environment, so holding it elsewhere would let an identity
# in that other account read the whole shape of this one — which cuts against the
# account separation the layout exists for. There is no longer a tooling-account
# exception: ECR moved here, and nothing else was ever in that account.
#
# Locking is S3 conditional writes (`use_lockfile`), not a DynamoDB table. Never
# set both — Terraform treats that as a conflict.
#
# A backend block cannot use variables or locals: Terraform evaluates it before the
# variable graph exists. This is the one place a literal account id is unavoidable.

terraform {
  backend "s3" {
    bucket       = "mbai-tfstate-058190633983"
    key          = "staging/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
