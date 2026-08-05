# State backend — the bucket and lock table created by ../bootstrap.
#
# A SEPARATE state key from every environment, which is the entire point of this
# directory: the registry is shared, so exactly one state may own it.
#
# Values are literal because a backend block cannot use variables or locals.

terraform {
  backend "s3" {
    bucket         = "mbai-tfstate-591554480818"
    key            = "shared/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mbai-tf-locks"
    encrypt        = true
  }
}
