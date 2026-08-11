#!/usr/bin/env bash
# Shared helpers for scripts/deploy.
#
# Sourced, never executed. Every function here is environment-agnostic: nothing
# knows the word "staging", no account id, no region, no domain. The caller passes
# an environment name, and every identifier is read back from `terraform output` or
# from that environment's own terraform.tfvars.
#
# TARGETS BASH 3.2 -- the version macOS ships. No associative arrays, no
# `read -i`, no `mapfile`, no `${x,,}`. Adding any of them breaks the script on the
# only machine that has ever run it.

# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$(printf '\033[0m'); C_BOLD=$(printf '\033[1m'); C_DIM=$(printf '\033[2m')
  C_RED=$(printf '\033[31m'); C_GREEN=$(printf '\033[32m')
  C_YELLOW=$(printf '\033[33m'); C_BLUE=$(printf '\033[34m')
else
  C_RESET=''; C_BOLD=''; C_DIM=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''
fi

info()   { printf '%s\n' "$*"; }
note()   { printf '%s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
ok()     { printf '%s  ok %s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
bad()    { printf '%sFAIL%s %s\n' "$C_RED" "$C_RESET" "$*"; }
warn()   { printf '%swarn%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
hr()     { printf '%s\n' "----------------------------------------------------------------------"; }

# A hazard is not a warning. It is a thing the ticket says has already gone wrong
# on this project at least once, and it gets the loud treatment.
hazard() { printf '%s%s!! %s%s\n' "$C_BOLD" "$C_YELLOW" "$*" "$C_RESET" >&2; }

die() {
  printf '\n%s%sSTOPPED%s %s\n' "$C_BOLD" "$C_RED" "$C_RESET" "$1" >&2
  shift
  # Remaining arguments are explanation lines -- the "why", never just the "what".
  while [ $# -gt 0 ]; do printf '        %s\n' "$1" >&2; shift; done
  exit 1
}

banner() { printf '\n%s%s== %s ==%s\n' "$C_BOLD" "$C_BLUE" "$*" "$C_RESET"; }

# "Print what it WOULD do, then do it." Every mutating step announces itself in
# this form first, so even a --yes run leaves a readable record of what changed.
would() { printf '%s  -> %s%s\n' "$C_BLUE" "$C_RESET" "$*"; }

# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #

# Explicit y/N. Anything other than y/yes is a no, including an empty line.
# ASSUME_YES short-circuits it but still prints, so the transcript shows the
# decision that was taken on the operator's behalf.
confirm() {
  local prompt="$1" reply
  if [ "${ASSUME_YES:-0}" = "1" ]; then
    printf '%s [y/N] %s(--yes)%s\n' "$prompt" "$C_DIM" "$C_RESET"
    return 0
  fi
  if [ ! -t 0 ]; then
    die "Cannot ask for confirmation: stdin is not a terminal." \
      "Re-run interactively, or pass --yes if this is automation and you accept" \
      "that every confirmation in this stage is answered yes."
  fi
  printf '%s%s [y/N]%s ' "$C_BOLD" "$prompt" "$C_RESET"
  read -r reply
  case "$reply" in
    y | Y | yes | YES | Yes) return 0 ;;
    *) return 1 ;;
  esac
}

# --------------------------------------------------------------------------- #
# Preconditions
# --------------------------------------------------------------------------- #

need_cmd() {
  local cmd="$1" hint="${2:-}"
  command -v "$cmd" >/dev/null 2>&1 || die \
    "Required command not found: $cmd" "${hint:-Install it and re-run.}"
}

need_buildx() {
  docker buildx version >/dev/null 2>&1 || die \
    "docker buildx is not available." \
    "The images stage builds for linux/arm64, and buildx is what makes --platform" \
    "reliable and what can verify the pushed manifest's architecture." \
    "Install the plugin:" \
    "  brew install docker-buildx" \
    "  mkdir -p ~/.docker/cli-plugins" \
    "  ln -sfn \$(brew --prefix)/opt/docker-buildx/bin/docker-buildx \\" \
    "         ~/.docker/cli-plugins/docker-buildx" \
    "Then check with: docker buildx version"
}

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

env_dir()       { printf '%s/infra/envs/%s' "$REPO_ROOT" "$1"; }
bootstrap_dir() { printf '%s/infra/bootstrap' "$REPO_ROOT"; }

list_envs() {
  local d
  for d in "$REPO_ROOT"/infra/envs/*/; do
    [ -d "$d" ] || continue
    basename "$d"
  done
}

# --------------------------------------------------------------------------- #
# terraform.tfvars reading
#
# Terraform exposes OUTPUTS, never inputs, so the phase flags and the domain can
# only be read from the environment's own tfvars. That file is the per-environment
# contract this whole script is built around: adding production means adding a
# tfvars file and a profile, not editing anything here.
#
# The parser is deliberately narrow -- `name = "value"` or `name = bare` on one
# line, with `#` comments stripped. Every value it is pointed at in this repo has
# that shape. It fails loudly rather than returning something plausible.
# --------------------------------------------------------------------------- #

tfvar() {
  local file="$1" name="$2" line value
  [ -f "$file" ] || die "No such file: $file"
  line=$(grep -E "^[[:space:]]*${name}[[:space:]]*=" "$file" | head -1 || true)
  [ -n "$line" ] || return 1
  value=${line#*=}
  value=${value%%#*}
  value=$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
  value=${value#\"}
  value=${value%\"}
  printf '%s' "$value"
}

tfvar_required() {
  local file="$1" name="$2" v
  v=$(tfvar "$file" "$name") || die \
    "\`$name\` is not set in $file" \
    "Every environment must declare it -- the deploy script reads it from there" \
    "rather than hardcoding a value for one environment."
  [ -n "$v" ] || die "\`$name\` is empty in $file"
  printf '%s' "$v"
}

# --------------------------------------------------------------------------- #
# AWS
# --------------------------------------------------------------------------- #

# Every AWS call goes through here so the profile and region are applied in
# exactly one place. Terraform picks the same profile up from the exported
# AWS_PROFILE.
awsx() { aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"; }

# The account guard. Terraform enforces the same thing as a plan precondition, but
# a wrong-profile `aws ecs run-task` or `put-secret-value` never reaches Terraform,
# so the check is repeated here for every stage that touches AWS at all.
require_identity() {
  local expected="$1" actual
  actual=$(awsx sts get-caller-identity --query Account --output text 2>/dev/null) || die \
    "Cannot reach AWS with profile '$AWS_PROFILE'." \
    "The SSO session has probably expired. Sessions are separate; one login does not" \
    "cover the others:" \
    "  aws sso login --sso-session mbai" \
    "A token that expires MID-APPLY fails partway and leaves half-created resources," \
    "so check the clock before starting a 10-15 minute apply."
  if [ "$actual" != "$expected" ]; then
    die "Wrong AWS account: profile '$AWS_PROFILE' is in $actual, environment '$ENV_NAME' is $expected." \
      "Refusing to touch the wrong account. Pass --profile NAME, or fix the profile's" \
      "account in ~/.aws/config."
  fi
  note "identity: account $actual via profile $AWS_PROFILE ($AWS_REGION)"
}

# --------------------------------------------------------------------------- #
# Terraform
# --------------------------------------------------------------------------- #

tf() { terraform -chdir="$1" "${@:2}"; }

# `use_lockfile` was never verified against the pinned Terraform, and the ticket is
# explicit that a rejection must stop the run rather than be worked around. The
# only workaround available is setting BOTH lock mechanisms, which Terraform treats
# as a conflict -- so this reports the documented fallback and exits.
init_or_explain_lockfile() {
  local dir="$1" label="$2" log rc
  log=$(mktemp "${TMPDIR:-/tmp}/deploy-init.XXXXXX")
  would "terraform -chdir=$dir init"
  set +e
  tf "$dir" init -input=false 2>&1 | tee "$log"
  rc=${PIPESTATUS[0]}
  set -e
  if [ "$rc" -eq 0 ]; then
    rm -f "$log"
    ok "$label: init"
    return 0
  fi
  if grep -qi "use_lockfile" "$log"; then
    rm -f "$log"
    die "terraform init rejected \`use_lockfile\`." \
      "This is the failure C4b predicted and left a documented fallback for. Apply it" \
      "by hand -- this script will not route around it, because the only silent" \
      "workaround is setting both lock mechanisms, which Terraform rejects as a" \
      "conflict:" \
      "" \
      "  1. In infra/envs/$ENV_NAME/backend.tf, replace" \
      "       use_lockfile = true" \
      "     with" \
      "       dynamodb_table = \"mbai-tf-locks\"" \
      "" \
      "  2. Restore the lock table in infra/bootstrap/main.tf:" \
      "" \
      "       resource \"aws_dynamodb_table\" \"locks\" {" \
      "         name         = \"mbai-tf-locks\"" \
      "         billing_mode = \"PAY_PER_REQUEST\"" \
      "         hash_key     = \"LockID\"" \
      "         attribute { name = \"LockID\"  type = \"S\" }" \
      "         lifecycle { prevent_destroy = true }" \
      "       }" \
      "" \
      "  3. Apply bootstrap BEFORE initialising the environment." \
      "" \
      "  NEVER set both -- Terraform treats that as a conflict." \
      "  Source: docs/tickets/C4b-consolidate-staging-result.md"
  fi
  rm -f "$log"
  die "terraform init failed in $dir (exit $rc)." "The error is above."
}

# plan with a detailed exit code: 0 = no changes, 2 = changes, anything else =
# error. This is what makes every terraform stage idempotent -- a re-run with
# nothing to do says so and exits clean instead of prompting for an empty apply.
tf_plan() {
  local dir="$1" planfile="$2" rc
  would "terraform -chdir=$dir plan -out=$(basename "$planfile")"
  set +e
  tf "$dir" plan -input=false -detailed-exitcode -out="$planfile"
  rc=$?
  set -e
  case "$rc" in
    0 | 2) return "$rc" ;;
    *) die "terraform plan failed in $dir (exit $rc)." "The error is above. Nothing was applied." ;;
  esac
}

# --------------------------------------------------------------------------- #
# terraform output
#
# Read once per run into a temp file, then queried with jq. One `terraform output`
# invocation instead of a dozen, and every identifier in this script comes from
# here rather than from a literal.
# --------------------------------------------------------------------------- #

TF_OUTPUT_CACHE=""

load_outputs() {
  local dir="$1"
  [ -n "$TF_OUTPUT_CACHE" ] && [ -f "$TF_OUTPUT_CACHE" ] && return 0
  TF_OUTPUT_CACHE=$(mktemp "${TMPDIR:-/tmp}/deploy-outputs.XXXXXX")
  if ! tf "$dir" output -json >"$TF_OUTPUT_CACHE" 2>/dev/null; then
    rm -f "$TF_OUTPUT_CACHE"; TF_OUTPUT_CACHE=""
    return 1
  fi
  # An un-applied environment yields `{}` -- valid JSON, no outputs.
  [ "$(jq -r 'length' "$TF_OUTPUT_CACHE")" = "0" ] && return 1
  return 0
}

require_outputs() {
  local dir="$1"
  load_outputs "$dir" || die \
    "No Terraform outputs for environment '$ENV_NAME'." \
    "The environment has not been applied yet, or this directory has not been" \
    "initialised. Run:  ./scripts/deploy $ENV_NAME phase1"
}

# Scalar output. Dies when absent, because every caller needs a real value and a
# silently-empty identifier produces an AWS error three steps later that names
# nothing.
out() {
  local name="$1" v
  v=$(jq -r --arg n "$name" \
    'if has($n) then (.[$n].value // "__ABSENT__") else "__ABSENT__" end' "$TF_OUTPUT_CACHE")
  if [ "$v" = "__ABSENT__" ]; then
    die "Terraform output '$name' is missing or null in environment '$ENV_NAME'." \
      "This environment's outputs.tf may not declare it -- envs/dev, for example, has" \
      "no DNS or Cognito outputs at all because it has no such modules."
  fi
  printf '%s' "$v"
}

# Optional scalar -- empty string when absent. For things that legitimately do not
# exist yet, such as certificate_arn before phase 2.
out_opt() {
  jq -r --arg n "$1" 'if has($n) then (.[$n].value // "") else "" end' \
    "$TF_OUTPUT_CACHE" 2>/dev/null || printf ''
}

# One key out of a map-valued output.
out_map() {
  local name="$1" key="$2" v
  v=$(jq -r --arg n "$name" --arg k "$key" \
    'if (has($n) and (.[$n].value | type) == "object" and (.[$n].value | has($k)))
     then .[$n].value[$k] else "__ABSENT__" end' "$TF_OUTPUT_CACHE")
  [ "$v" = "__ABSENT__" ] && die \
    "Terraform output '$name[\"$key\"]' is missing in environment '$ENV_NAME'."
  printf '%s' "$v"
}

# Non-fatal map lookup -- empty string when the output or key is absent. `status`
# reports on every stage including ones that have not run, so it cannot use the
# dying variant.
out_map_opt() {
  jq -r --arg n "$1" --arg k "$2" \
    'if (has($n) and (.[$n].value | type) == "object" and (.[$n].value | has($k)))
     then (.[$n].value[$k] // "") else "" end' "$TF_OUTPUT_CACHE" 2>/dev/null || printf ''
}

# Elements of a list-valued output, one per line.
out_list() {
  jq -r --arg n "$1" 'if has($n) then (.[$n].value[]) else empty end' "$TF_OUTPUT_CACHE"
}

# First element only. Done in jq rather than `out_list | head -1`, because head
# closes the pipe after one line and jq can then die of SIGPIPE — which pipefail
# turns into a failed assignment and set -e turns into a silent exit.
out_list_first() {
  jq -r --arg n "$1" 'if has($n) then (.[$n].value[0] // "") else "" end' "$TF_OUTPUT_CACHE"
}

# The env-level log_group_names output is a LIST of full paths (/ecs/<prefix>/api
# and so on), while modules/data also exposes a keyed map. Accept either shape and
# pick the group whose trailing segment matches.
log_group_for() {
  local key="$1" v
  v=$(jq -r --arg k "$key" '
        .log_group_names.value as $g
        | if ($g | type) == "object" then ($g[$k] // "")
          else ([$g[] | select(endswith("/" + $k))] | first // "")
          end' "$TF_OUTPUT_CACHE" 2>/dev/null || printf '')
  { [ -n "$v" ] && [ "$v" != "null" ]; } || die \
    "Could not find the '$key' CloudWatch log group in the log_group_names output."
  printf '%s' "$v"
}

# --------------------------------------------------------------------------- #
# ECR image URIs
#
# The task definitions reference exactly the URIs in container_image_uris, so that
# output is the single source of truth for what to build, tag and push. Nothing is
# reassembled from an account id or a region.
# --------------------------------------------------------------------------- #

uri_registry() { printf '%s' "${1%%/*}"; }                     # <acct>.dkr.ecr.<region>.amazonaws.com
uri_repo()     { local r="${1#*/}"; printf '%s' "${r%:*}"; }   # mbai/api
uri_tag()      { printf '%s' "${1##*:}"; }                     # staging

# --------------------------------------------------------------------------- #
# DNS
# --------------------------------------------------------------------------- #

# Delegation is live when the registrar hands back four AWS nameservers. Anything
# else -- no answer, the registrar's own parking nameservers, two of four
# mid-propagation -- is "not yet", and phase 2 must not run on it.
#
# `|| true` is load-bearing: `grep -c` exits 1 when the count is ZERO, and under
# `set -o pipefail` that makes the whole pipeline — and this function — return 1.
# The caller writes `count=$(ns_awsdns_count "$d")`, so under `set -e` the script
# would abort silently on exactly the case this exists to detect: no delegation
# yet. Verified: it aborted with no message before this was added.
ns_awsdns_count() {
  local n
  n=$(dig +short NS "$1" 2>/dev/null | grep -c 'awsdns' || true)
  n=$(printf '%s' "$n" | tr -d '[:space:]')
  [ -n "$n" ] || n=0
  printf '%s' "$n"
}

# --------------------------------------------------------------------------- #
# Secrets Manager
# --------------------------------------------------------------------------- #

# Byte length of a secret's current value, or empty when it has no value yet.
# NEVER prints, returns or logs the value itself.
secret_len() {
  local id="$1" v
  v=$(awsx secretsmanager get-secret-value --secret-id "$id" \
    --query 'SecretString' --output text 2>/dev/null) || { printf ''; return 0; }
  { [ "$v" = "None" ] || [ -z "$v" ]; } && { printf ''; return 0; }
  printf '%s' "${#v}"
}

# Writes a secret without ever putting the value on a command line -- `ps` on a
# shared machine shows the full argv of a running process, and a
# `--secret-string "$X"` invocation also lands in shell history. file:// reads it
# from a 0600 file that the run's trap deletes.
put_secret() {
  local id="$1" value="$2" f
  f="$SECRET_TMPDIR/payload.$$"
  ( umask 077; printf '%s' "$value" >"$f" )
  awsx secretsmanager put-secret-value --secret-id "$id" \
    --secret-string "file://$f" >/dev/null
  rm -f "$f"
}

# --------------------------------------------------------------------------- #
# Fernet
#
# The failure mode the ticket names: encryption-key is length-validated but not
# format-validated at boot, so a malformed value starts cleanly and fails at the
# FIRST SSN write, inside a request handler. So the key is generated and validated
# by a Python that actually has `cryptography` -- the same library the application
# uses. A structural check (44 chars, urlsafe base64) would accept values Fernet
# rejects.
# --------------------------------------------------------------------------- #

find_fernet_python() {
  local c
  for c in "$REPO_ROOT/backend/.venv/bin/python" python3 python; do
    if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
      if "$c" -c 'from cryptography.fernet import Fernet' >/dev/null 2>&1; then
        printf '%s' "$c"; return 0
      fi
    fi
  done
  return 1
}

require_fernet_python() {
  local p
  p=$(find_fernet_python) || die \
    "No Python with the \`cryptography\` package is available." \
    "encryption-key must be a real Fernet key, and the only honest way to check that" \
    "is to construct one. A length check would pass values Fernet rejects at the" \
    "first SSN write, inside a request handler." \
    "Fix:  cd backend && uv sync   (this looks for backend/.venv/bin/python first)"
  printf '%s' "$p"
}
