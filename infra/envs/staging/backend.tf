# State backend. Same bucket and lock table as every other environment, with its
# own key — one state file per environment.
#
# A backend block cannot use variables or locals: Terraform evaluates it before the
# variable graph exists. This is the one place in the environment where literals are
# unavoidable.

terraform {
  backend "s3" {
    bucket         = "mbai-tfstate-591554480818"
    key            = "staging/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mbai-tf-locks"
    encrypt        = true
  }
}
