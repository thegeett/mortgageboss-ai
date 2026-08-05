# `envs/staging` — not built yet

Ticket C2 builds **dev**. This directory holds only
`terraform.tfvars.example`, to prove the modules take staging values without a
single module edit — the acceptance test for §6b of the ticket.

## To build staging

`main.tf`, `variables.tf` and `outputs.tf` are **copies of `../dev/`, unchanged.**
Only three things differ:

1. `terraform.tfvars` — copied from `terraform.tfvars.example` here and filled in.
2. `backend.tf` — same bucket and lock table, but `key = "staging/terraform.tfstate"`.
3. The account id, if staging lives in a different AWS account.

If building staging ever requires editing something under `../../modules/`, that
is a defect in the module, not a staging requirement.

## The differences that matter

| Setting | dev | staging | Why |
|---|---|---|---|
| `rds_multi_az` | `false` | **`true`** | Single-AZ is a dev economy. |
| `rds_deletion_protection` | `false` | **`true`** | Staging holds real borrower NPI. |
| `rds_skip_final_snapshot` | `true` | **`false`** | A destroy must leave a recovery point. |
| `secret_recovery_window_days` | `0` | **`30`** | Zero makes a fat-fingered destroy unrecoverable. |
| `ecr_force_delete` | `true` | **`false`** | Destroy must not silently discard image history. |
| `enable_nat_gateway` | `true` | **`false`** | ⬇ |
| `enable_vpc_endpoints` | `false` | **`true`** | Egress must never touch the public internet. |
| `vpc_cidr` | `10.20.0.0/16` | **`10.30.0.0/16`** | Identical ranges cannot be peered. |
| `redis_auth_enabled` | `false` | **`true`** | Makes `REDIS_URL` a secret; defence in depth. |

## ⚠️ Before applying staging

Verify the Bedrock interface endpoint exists — staging turns endpoints on and NAT
off, so a missing endpoint means tasks cannot reach Bedrock at all:

```bash
aws ec2 describe-vpc-endpoint-services \
  --query "ServiceNames[?contains(@,'bedrock')]" --output text
```

This was **not** verifiable while C2 was written — the available role
(`BedrockDeveloper`) lacks `ec2:DescribeVpcEndpointServices`. See
`docs/tickets/C2-terraform-result.md`.
