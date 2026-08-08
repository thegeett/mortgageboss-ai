aws_region     = "us-east-1"
aws_account_id = "591554480818"

# Two repositories, not three: C1 established that the API and the Celery worker
# run the SAME image with different commands.
ecr_repository_names = ["mbai/api", "mbai/frontend"]

# Counted across every environment now that the registry is shared, so this tier
# is burned through by CI. It does NOT protect a promoted tag — that is what
# ecr_protected_tag_prefixes is for.
ecr_keep_last_images     = 30
ecr_untagged_expire_days = 7

# Promoted images matched by a higher-priority rule, so they never enter the count
# above. Without this a busy dev pipeline evicts the oldest image in the registry —
# which is exactly the tag staging is running.
ecr_protected_tag_prefixes     = ["staging-", "prod-", "release-"]
ecr_keep_last_protected_images = 20

# false, deliberately. See the variable description: a forced destroy here loses
# every environment's image history, not one environment's.
ecr_force_delete = false

# The staging workload account. It runs in a DIFFERENT account from this registry,
# so it needs an explicit pull grant — the repository policy and the kms:Decrypt on
# the image key are both driven from this list.
ecr_pull_account_ids = ["058190633983"]
