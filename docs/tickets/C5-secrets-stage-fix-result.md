# C5 — secrets stage fixes

**Date:** 2026-08-12
**Input:** [`docs/findings/secrets-stage-input.md`](../findings/secrets-stage-input.md) §3
**Outcome:** the secrets stage can accept input again, builds valid Redis URLs, and
now refuses to write a `REDIS_URL` that contradicts the cluster's real auth state.

The secrets stage was **not** run. No secret was written. No `terraform apply`.

---

## 1 — `prompt_with_suggestion` wrote its prompt to stdout

`scripts/deploy`. The caller reads the function through a command substitution:

```bash
url=$(prompt_with_suggestion "DATABASE_URL" "$suggestion")
```

which captures **stdout** — so every `info` line of the prompt was swallowed into
the variable and the operator's typed value was appended to it. The operator saw no
prompt, and the validator received 260 bytes of prompt text followed by a perfectly
valid URL.

**Fixed:** the prompt block is wrapped in `{ … } >&2`. Only the value reaches stdout.

```bash
  {
    info ""
    info "  ${C_BOLD}${label}${C_RESET}"
    info "  suggested (from terraform output):"
    info "    ${suggestion}"
    info "  Press Enter to accept, or paste the corrected value."
    printf '  %s> ' "$label"
  } >&2
```

The comment above it records *why* — including the reported symptom — so the next
person editing this function does not undo it by adding one more `info` line outside
the block.

**Verified.** A piped paste of a 130-byte URL:

```
### CAPTURED len=130
0000000    p   o   s   t   g   r   e   s   q   l   +   a   s   y   n   c
0000020    p   g   :   /   /   m   b   a   i   _   a   d   m   i   n   :
0000040    S   b   !   x   (   y   ;   z   )   Q   @   m   b   a   i   -
### byte-identical to what was piped in?  YES - exact match
### VALIDATOR: ACCEPTED
```

Run again with `2>/dev/null`, stdout carries **only** those 130 bytes — nothing from
the prompt leaks into the captured value.

---

## 3 — `read -r` → `read -r -e`

Readline on, so a 130-character URL can be edited rather than only retyped.

⚠️ Checked before relying on it, because the stage is sometimes driven with piped
input: with non-terminal stdin, `-e` degrades to a plain read and still returns the
piped line intact (bash 3.2, verified). `read -i` remains unavailable in bash 3.2, so
the suggestion still cannot be pre-loaded into the line editor — pressing Enter
accepts it verbatim, and a value still containing `<PASSWORD>` fails validation
rather than being written.

---

## 2 — `redis_url_scheme` is `rediss`, not `rediss://`

`modules/data/outputs.tf` has `value = "rediss"` while its description read
*"Always rediss://"*. The stage believed the description and concatenated:

| branch | built | result |
|---|---|---|
| auth on | `"${scheme}:<AUTH_TOKEN>@…"` | `rediss:<AUTH_TOKEN>@master…` — no `//` |
| auth off | `"${scheme}${endpoint}…"` | `redissmaster.mbai-staging…` — scheme fused to host |

Both were rejected by `validate_redis_url`, which requires `rediss://` — so it failed
safe, but the suggested value could never be accepted by pressing Enter.

**Fixed in the consumer:**

```bash
scheme=$(out_opt redis_url_scheme); [ -n "$scheme" ] || scheme="rediss"
scheme="${scheme%://}"          # tolerate either spelling, now and later
…
suggestion="${scheme}://:<AUTH_TOKEN>@${endpoint}:6379/0?ssl_cert_reqs=required"
suggestion="${scheme}://${endpoint}:6379/0?ssl_cert_reqs=required"
```

Stripping a trailing `://` before adding one means the code is correct whichever
spelling the output ever carries.

**Fixed in the description**, per instruction — the value is unchanged, so there is
no plan diff (output descriptions are not persisted in state):

- `infra/modules/data/outputs.tf` — now states the value is the **bare** string and
  that a consumer must add the separator, and records that the old wording is what
  produced the malformed URLs.
- `infra/envs/staging/outputs.tf` and `infra/envs/dev/outputs.tf` — the same
  inaccurate one-liner was duplicated in both env-level passthroughs. Corrected in
  both; leaving them would have left the misleading sentence in the file an operator
  actually reads.

---

## 4 — The Redis AUTH mismatch now fails here instead of in the worker

### The inconsistency

| fact | source | value today |
|---|---|---|
| `redis_requires_auth_token` | terraform output (`var.redis_auth_enabled`) | **true** |
| `AuthTokenEnabled` | the live replication group | **False** |

They are different things. The first is what the configuration was told to expect —
and it also decides whether the `redis-url` **secret** exists at all. The second is
what the cluster actually has. The token is applied **out of band**, by hand, so it
starts false and stays false until someone does it. Terraform does not manage it and
cannot reconcile them.

The old code read only the terraform output, suggested a URL containing
`<AUTH_TOKEN>`, and would have written whatever the operator supplied. The mismatch
then surfaced in the **worker**, as an authentication error, with nothing in it
pointing back at the secret.

### What was added

Four helpers plus two assertions in the `redis-url` branch:

| function | does |
|---|---|
| `redis_auth_token_enabled` | reads live `AuthTokenEnabled`; `True`/`False`/empty |
| `redis_replication_group_id` | resolves the group id for the remediation command |
| `redis_apply_token_instructions` | prints the exact `modify-replication-group` invocation |
| `assert_redis_auth_agrees` | **before prompting** — terraform's expectation vs reality |
| `redis_url_has_credential` | does a URL carry userinfo? path and query stripped first |
| `assert_redis_credential_matches` | **after prompting** — the supplied value vs reality |

Two assertions rather than one, because the operator can paste something other than
the suggestion. The first stops the stage before asking for a value that cannot be
written; the second checks what was actually typed.

**Looked up by matching the primary endpoint, not by guessing the id.** The endpoint
is already a terraform output, so nothing depends on the replication group being
named after `name_prefix`:

```bash
--query "ReplicationGroups[?NodeGroups[?PrimaryEndpoint.Address=='${endpoint}']].AuthTokenEnabled | [0]"
```

Verified live: returns `False` for the real endpoint, `None` (→ empty) for an unknown
one.

### The four cases

| terraform | cluster | behaviour |
|---|---|---|
| `true` | `False` | **refuse**, with the token command — today's state |
| `true` | `True` | proceed; suggestion carries `<AUTH_TOKEN>` |
| `false` | `True` | warn: a credential-less URL will be refused at connect |
| any | unreadable | warn and proceed — a failed describe must not block the stage |

and, on the value actually supplied:

| URL | cluster | behaviour |
|---|---|---|
| carries a credential | `False` | **refuse** — the ask from the report |
| carries none | `True` | **refuse** — the symmetric error |
| matches | — | proceed |

Unknown cluster state skips both checks rather than guessing.

### What the operator sees today

```
!! TERRAFORM AND THE CLUSTER DISAGREE ABOUT REDIS AUTH.

  redis_requires_auth_token (terraform) : true
  AuthTokenEnabled (live cluster)       : False

  The token is applied out of band and has not been applied. A
  token-bearing REDIS_URL written now would pass every check in this
  stage and then fail in the WORKER -- redis-py and kombu both raise an
  authentication error against a cluster that has no token, and nothing
  in that error points back at this secret.

  Apply the token (16-128 printable ASCII, no / " @ or %):

    TOKEN=$(LC_ALL=C tr -dc 'A-Za-z0-9!*()-_=+.,;~' </dev/urandom | head -c 32)
    aws elasticache modify-replication-group \
      --replication-group-id mbai-staging \
      --auth-token "$TOKEN" \
      --auth-token-update-strategy ROTATE \
      --apply-immediately

  ROTATE, not SET: the AWS CLI documents SET as "allowed only after
  ROTATE", and this group has no token yet. …

STOPPED Refusing to populate redis-url while the cluster has no AUTH token.
        Nothing was written. Apply the token, or change the configuration.
```

The `mbai-staging` in that command is resolved live, not templated.

⚠️ **Consequence:** `./scripts/deploy staging secrets` will now stop at `redis-url`
until the AUTH token is applied. That is the intended behaviour — it is the check
that did not exist. `database-url`, `jwt-secret-key` and `encryption-key` are
processed before it and are unaffected.

The token constraints in the message are quoted from
`aws elasticache modify-replication-group help`, not from memory: printable ASCII,
16–128 characters, no `/`, `"`, `@` or `%`; `--auth-token` requires
`--auth-token-update-strategy`; `SET` is documented as *"allowed only after ROTATE"*,
which is why a cluster with no token uses `ROTATE`.

---

## Verification

```
bash -n scripts/deploy                     OK
bash -n scripts/deploy-lib.sh              OK
./scripts/deploy --help                    OK
terraform fmt -recursive -check            exit 0
validate: bootstrap / envs/staging / envs/dev   Success (all three)
```

**Scratch harness, 20 assertions, all passing** — live AWS lookups plus every
simulated auth state:

```
== live lookup ==
  ok  AuthTokenEnabled via endpoint match       False
  ok  ReplicationGroupId via endpoint match     mbai-staging
  ok  unknown endpoint -> empty
== scheme concatenation (output is bare 'rediss') ==
  auth   : rediss://:<AUTH_TOKEN>@master.mbai-staging.…:6379/0?ssl_cert_reqs=required
  no-auth: rediss://master.mbai-staging.…:6379/0?ssl_cert_reqs=required
  ok  no-auth suggestion passes validator
  ok  auth suggestion rejected (placeholder still present)
  ok  real token URL passes
  ok  tolerates an output that DOES include ://
== redis_url_has_credential ==
  ok  token URL / no-credential URL / user:pass form
  ok  '@' only in the query is not a credential
== assert_redis_auth_agrees ==
  ok  terraform=true, cluster=False -> REFUSE
  ok  terraform=true, cluster=True  -> ok
  ok  terraform=false, cluster=True -> warn
  ok  cluster unknown -> warn, proceed
== assert_redis_credential_matches ==
  ok  token URL + cluster has NO token   -> REFUSE
  ok  bare URL  + cluster REQUIRES token -> REFUSE
  ok  token URL + cluster has token -> ok
  ok  bare URL  + cluster no token  -> ok
  ok  unknown cluster state -> skip
```

Only read-only AWS calls were made (`describe-replication-groups`,
`terraform output`). Harness files were written outside the repo.

---

## What still needs doing, in order

1. `printf '%s' 'YOUR_COPY' | shasum -a 256 | cut -c1-12` → expect `77892c47d94f`.
   The password has **no `)`** in it; the earlier transcription had one.
2. Apply the ElastiCache AUTH token (the command the stage now prints), and wait for
   `AuthTokenEnabled: true`.
3. `./scripts/deploy staging secrets` — it will prompt properly now, generate
   `jwt-secret-key` and `encryption-key`, and accept both URLs.
4. Store the printed Fernet key outside AWS. There is no rotation path until B2.

Do **not** percent-encode the database password: the generator's `override_special`
excludes `%` precisely so the value pastes into a URL literally
(`modules/data/main.tf`), and SQLAlchemy percent-decodes userinfo on parse, so
encoding only adds a way to get it subtly wrong.
