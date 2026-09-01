#!/usr/bin/env bash
set -euo pipefail

ACCOUNT_URL="sfsenorthamerica-rgoldin-aws1.snowflakecomputing.com"
SPCS_HOST="m2p7lf-sfsenorthamerica-rgoldin-aws1.snowflakecomputing.app"
ROLE="FLAKEBENCH_APP_GUEST_RL"

usage() {
  cat <<EOF
Usage: $0 <PAT> [path] [curl-flags...]

Authenticate to FlakeBench SPCS via PAT and make a request.

  PAT        Programmatic Access Token for the FLAKEBENCH user
  path       Request path (default: /)
  curl-flags Extra flags passed to the final curl (e.g. -X POST -d '{}')

Examples:
  $0 eyJra...  /health
  $0 eyJra...  /api/benchmarks -X POST -d '{"query":"test"}'
  $0 eyJra...  /                -o page.html

Environment overrides:
  SPCS_ACCOUNT_URL   (default: $ACCOUNT_URL)
  SPCS_ENDPOINT_HOST (default: $SPCS_HOST)
  SPCS_ROLE          (default: $ROLE)
EOF
  exit 1
}

[[ $# -lt 1 ]] && usage

PAT="$1"
PATH_ARG="${2:-/}"
shift; [[ $# -ge 1 ]] && shift
EXTRA_ARGS=("$@")

ACCOUNT_URL="${SPCS_ACCOUNT_URL:-$ACCOUNT_URL}"
SPCS_HOST="${SPCS_ENDPOINT_HOST:-$SPCS_HOST}"
ROLE="${SPCS_ROLE:-$ROLE}"

TOKEN_URL="https://${ACCOUNT_URL}/oauth/token"
APP_URL="https://${SPCS_HOST}${PATH_ARG}"

echo ":: Exchanging PAT for ingress token (role=${ROLE})..." >&2

ACCESS_TOKEN=$(curl -sf -X POST "${TOKEN_URL}" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=${PAT}" \
  -d "subject_token_type=programmatic_access_token" \
  -d "scope=session:scope:${ROLE} ${SPCS_HOST}")

if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "ERROR: Token exchange failed." >&2
  exit 1
fi

echo ":: Token obtained (expires in ~1h). Requesting ${APP_URL}..." >&2

curl -s \
  -H "Authorization: Snowflake Token=\"${ACCESS_TOKEN}\"" \
  "${APP_URL}" \
  "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
