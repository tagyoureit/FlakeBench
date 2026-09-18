#!/usr/bin/env bash
# Deploy FlakeBench to SPCS without changing the public URL.
#
# The stable URL comes from the Snowflake Gateway (FLAKEBENCH_GATEWAY), not from
# SHOW ENDPOINTS — the raw service ingress changes on every ALTER SERVICE.
#
# Usage: ./spcs/deploy.sh [TAG]        (default tag: latest)
#        SKIP_CSS=1 ./spcs/deploy.sh   (skip the Tailwind rebuild)
#
# Requires: Snowflake VPN (the account network policy blocks non-VPN IPs).

set -euo pipefail

TAG="${1:-latest}"
CONNECTION="${SNOWFLAKE_CONNECTION:-sfsenorthamerica-rgoldin_aws1}"
REGISTRY="sfsenorthamerica-rgoldin-aws1.registry.snowflakecomputing.com/sandbox/spcs/flakebench_repo"
IMAGE="flakebench"
SERVICE="SANDBOX.SPCS.FLAKEBENCH_SERVICE"
REPOSITORY="SANDBOX.SPCS.FLAKEBENCH_REPO"
GATEWAY="SANDBOX.SPCS.FLAKEBENCH_GATEWAY"
CONTAINER="flakebench"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC_FILE="${REPO_ROOT}/spcs/service-spec.yaml"
CURRENT_STEP=""

# --- Helpers ----------------------------------------------------------------

die() { echo "FATAL: $*" >&2; exit 1; }

step() {
    CURRENT_STEP="$1"
    echo ""
    echo "==> $1"
}

sf() { snow sql --connection "${CONNECTION}" "$@"; }

on_error() {
    local exit_code=$?
    echo "" >&2
    echo "ERROR: Failed during: ${CURRENT_STEP:-unknown step} (exit code ${exit_code})" >&2
    echo "" >&2
    echo "==> Fetching recent service logs for diagnosis..." >&2
    sf -q "SELECT SYSTEM\$GET_SERVICE_LOGS('${SERVICE}', 0, '${CONTAINER}', 50)" 2>/dev/null || true
    echo "" >&2
    echo "==> Current service status:" >&2
    sf -q "SELECT SYSTEM\$GET_SERVICE_STATUS('${SERVICE}')" 2>/dev/null || true
    exit "${exit_code}"
}
trap on_error ERR

# Pull a single column value out of `snow sql --format json` output.
json_field() {
    python3 -c '
import json,sys
rows=json.load(sys.stdin)
while isinstance(rows,list) and rows and isinstance(rows[0],list):
    rows=rows[0]
key=sys.argv[1].lower()
for row in rows:
    if not isinstance(row,dict):
        continue
    for k,v in row.items():
        if k.lower()==key:
            print(v); sys.exit(0)
' "$1" 2>/dev/null || true
}

# --- Pre-flight checks ------------------------------------------------------

step "Pre-flight checks"
[[ -f "${SPEC_FILE}" ]] || die "spec file not found: ${SPEC_FILE}"
command -v docker  >/dev/null 2>&1 || die "docker is not installed or not in PATH"
command -v snow    >/dev/null 2>&1 || die "snow CLI is not installed or not in PATH"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed or not in PATH"

if ! docker info >/dev/null 2>&1; then
    echo "    Docker daemon not running — starting /Applications/Docker.app ..."
    open -a /Applications/Docker.app
    max_wait=60
    elapsed=0
    while ! docker info >/dev/null 2>&1; do
        sleep 2
        elapsed=$((elapsed + 2))
        [[ ${elapsed} -ge ${max_wait} ]] && die "Docker daemon did not start within ${max_wait}s"
    done
    echo "    Docker daemon started (took ~${elapsed}s)"
else
    echo "    Docker daemon already running"
fi
echo "    docker, snow CLI, python3, and Docker daemon OK"

# --- Build Tailwind CSS ------------------------------------------------------
# backend/static/css/tailwind.css is gitignored but IS baked into the image via
# COPY backend/. Editing input.css without rebuilding ships stale CSS.

if [[ "${SKIP_CSS:-0}" == "1" ]]; then
    step "Skipping Tailwind CSS build (SKIP_CSS=1)"
else
    step "Building Tailwind CSS"
    (cd "${REPO_ROOT}" && task css:build)
fi

# --- Registry login (before build so auth failures surface early) ------------

step "Logging in to Snowflake registry"
snow spcs image-registry login --connection "${CONNECTION}"

# --- Build -------------------------------------------------------------------

step "Building image for linux/amd64 (--no-cache)"
docker build --no-cache --platform linux/amd64 --load -t "${IMAGE}:${TAG}" "${REPO_ROOT}"

step "Tagging for Snowflake registry"
docker tag "${IMAGE}:${TAG}" "${REGISTRY}/${IMAGE}:${TAG}"

step "Pushing image"
docker push "${REGISTRY}/${IMAGE}:${TAG}"

# --- Build the ALTER SERVICE spec from service-spec.yaml ---------------------
# service-spec.yaml is the canonical source — never hand-type the spec.
# Transformations only:
#   1. Drop externalAccessIntegrations (not valid in an ALTER SERVICE spec body;
#      EAIs are a service property, set separately below).
#   2. Strip comments and blank lines. Required, not cosmetic: the file's header
#      comment contains the literal "$$<contents>$$", which would close the SQL
#      dollar-quoted block early and produce a syntax error.
#   3. Rewrite the image tag if a non-default TAG was requested.
#   4. Drop keys left with no children (e.g. the `secrets:` example block) — they
#      would otherwise serialize as `key: null` and be rejected.

step "Preparing service specification from spcs/service-spec.yaml"
SPEC=$(
    awk '/^[[:space:]]*externalAccessIntegrations:/ {exit} {print}' "${SPEC_FILE}" \
        | sed -E '/^[[:space:]]*#/d; /^[[:space:]]*$/d' \
        | sed -E "s#(image:[[:space:]]*/SANDBOX/SPCS/FLAKEBENCH_REPO/${IMAGE}):.*#\1:${TAG}#" \
        | python3 -c '
import re, sys

lines = sys.stdin.read().splitlines()
drop = set()
for i, line in enumerate(lines):
    m = re.match(r"^(\s*)([A-Za-z][\w-]*):\s*$", line)
    if not m:
        continue
    indent = len(m.group(1))
    # Look ahead for a real (non-comment, non-blank) child at deeper indent.
    for nxt in lines[i + 1:]:
        if not nxt.strip():
            continue
        nxt_indent = len(nxt) - len(nxt.lstrip())
        stripped = nxt.lstrip()
        # A sequence item at the same indent is still a child of the key.
        if nxt_indent == indent and stripped.startswith("- "):
            break         # real child found -> keep the key
        if nxt_indent <= indent:
            drop.add(i)   # next key is a sibling/parent -> no children at all
            break
        if stripped.startswith("#"):
            continue      # comment-only child, keep looking
        break             # real child found -> keep the key
    else:
        drop.add(i)       # end of document reached with no real child
print("\n".join(l for i, l in enumerate(lines) if i not in drop))
'
)
grep -q "^  - name: app$" <<<"${SPEC}" \
    || die "spec is missing endpoint 'app' — the gateway targets ${SERVICE}!app"
case "${SPEC}" in
    *'$$'*) die "spec contains '\$\$' — it would terminate the SQL dollar-quote early" ;;
esac
grep -q ":${TAG}\$" <<<"$(grep 'image:' <<<"${SPEC}")" \
    || die "spec image tag was not rewritten to '${TAG}'"
echo "    endpoint 'app' present, image tag '${TAG}' OK"

# --- Update service ----------------------------------------------------------
# ALTER SERVICE is what re-resolves the tag to a digest. A docker push alone
# leaves the service running the previously frozen digest.

step "Updating service in place (preserves gateway URL)"
sf -q "ALTER SERVICE ${SERVICE} FROM SPECIFICATION \$\$
${SPEC}
\$\$;"

step "Attaching external access integrations"
sf -q "ALTER SERVICE ${SERVICE} SET EXTERNAL_ACCESS_INTEGRATIONS = (SNOWFLAKE_EAI, POSTGRES_EAI);"

# --- Wait for READY ---------------------------------------------------------

step "Waiting for service to reach READY (up to 3 min)"
MAX_ATTEMPTS=12
SLEEP_SECONDS=15
READY=0
for i in $(seq 1 "${MAX_ATTEMPTS}"); do
    RAW=$(sf -q "SELECT SYSTEM\$GET_SERVICE_STATUS('${SERVICE}')" --format json 2>/dev/null || true)

    # The status JSON is nested with escaped quotes (\"status\":\"READY\").
    if grep -q 'status.*READY' <<<"${RAW}"; then
        echo "    Service is READY"
        READY=1
        break
    fi

    INNER_STATUS=$(grep -o '"status[^,]*' <<<"${RAW}" | head -1 || true)
    echo "    Attempt ${i}/${MAX_ATTEMPTS} - ${INNER_STATUS:-status unknown}"
    sleep "${SLEEP_SECONDS}"
done

if [[ ${READY} -ne 1 ]]; then
    echo "" >&2
    echo "==> Service did not reach READY within $((MAX_ATTEMPTS * SLEEP_SECONDS))s." >&2
    echo "    Fetching logs for diagnosis..." >&2
    sf -q "SELECT SYSTEM\$GET_SERVICE_LOGS('${SERVICE}', 0, '${CONTAINER}', 50)" 2>/dev/null || true
    echo "" >&2
    echo "    Manual checks:" >&2
    echo "    snow sql -q \"SELECT SYSTEM\$GET_SERVICE_STATUS('${SERVICE}')\"" >&2
    echo "    snow sql -q \"SELECT SYSTEM\$GET_SERVICE_LOGS('${SERVICE}', 0, '${CONTAINER}', 50)\"" >&2
    exit 1
fi

# --- Verify the running digest matches the pushed image ----------------------
# "Statement executed successfully" only means the spec was accepted. Confirm the
# container actually came up on the image we just pushed.

step "Verifying running container digest matches the pushed image"
REPO_DIGEST=$(sf -q "SHOW IMAGES IN IMAGE REPOSITORY ${REPOSITORY}" --format json 2>/dev/null \
    | python3 -c '
import json,sys
rows=json.load(sys.stdin)
while isinstance(rows,list) and rows and isinstance(rows[0],list):
    rows=rows[0]
tag=sys.argv[1]
for row in rows:
    if not isinstance(row,dict):
        continue
    low={k.lower():v for k,v in row.items()}
    tags=str(low.get("tags",""))
    if tag in [t.strip() for t in tags.split(",")]:
        print(low.get("digest","")); sys.exit(0)
' "${TAG}" 2>/dev/null || true)

CONTAINER_JSON=$(sf -q "SHOW SERVICE CONTAINERS IN SERVICE ${SERVICE}" --format json 2>/dev/null || true)
RUN_DIGEST=$(json_field image_digest <<<"${CONTAINER_JSON}")
START_TIME=$(json_field start_time <<<"${CONTAINER_JSON}")

echo "    pushed  : ${REPO_DIGEST:-<unknown>}"
echo "    running : ${RUN_DIGEST:-<unknown>}"
echo "    started : ${START_TIME:-<unknown>}"

if [[ -n "${REPO_DIGEST}" && -n "${RUN_DIGEST}" ]]; then
    if [[ "${REPO_DIGEST}" == "${RUN_DIGEST}" ]]; then
        echo "    Digest match — the new image is live"
    else
        echo "" >&2
        echo "WARNING: running digest does not match the pushed ${TAG} image." >&2
        echo "         The service may still be rolling out — re-check with:" >&2
        echo "         snow sql -q \"SHOW SERVICE CONTAINERS IN SERVICE ${SERVICE}\"" >&2
    fi
else
    echo "    (could not resolve one of the digests — verify manually with"
    echo "     SHOW SERVICE CONTAINERS IN SERVICE ${SERVICE})"
fi

# --- Report URLs -------------------------------------------------------------

step "Endpoints"
sf -q "SHOW ENDPOINTS IN SERVICE ${SERVICE}"

echo ""
echo "==> Gateway (stable) URL:"
GATEWAY_URL=$(sf -q "DESC GATEWAY ${GATEWAY}" --format json 2>/dev/null \
    | grep -o '"ingress_url"[[:space:]]*:[[:space:]]*"[^"]*"' \
    | head -1 \
    | sed 's/.*"ingress_url"[[:space:]]*:[[:space:]]*"//;s/"//' || true)
if [[ -n "${GATEWAY_URL}" ]]; then
    echo "    https://${GATEWAY_URL}"
else
    echo "    (could not resolve — run: DESC GATEWAY ${GATEWAY})"
fi
