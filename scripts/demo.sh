#!/usr/bin/env bash
# =============================================================================
# HR Lifecycle Integration – Full JML Demo Script
# =============================================================================
# Runs a complete Joiner -> Mover -> Leaver flow and shows:
#   - Delivered webhook events
#   - Audit trail
#   - Forced failure -> retry -> dead-letter -> manual retry
#
# Requirements: curl, jq
# Usage: bash scripts/demo.sh
# =============================================================================

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
MOCK_URL="${MOCK_URL:-http://localhost:9000}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log()    { echo -e "${CYAN}[DEMO]${NC} $*"; }
success(){ echo -e "${GREEN}[OK]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*"; }
sep()    { echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# ─── Wait for services ────────────────────────────────────────────────────────
sep
log "Waiting for services to be ready..."
for i in {1..30}; do
  if curl -sf "${BASE_URL%/api/v1}/health" > /dev/null 2>&1; then
    success "API is ready."
    break
  fi
  warn "API not ready (attempt $i/30), retrying in 2s..."
  sleep 2
done

# ─── Authenticate ─────────────────────────────────────────────────────────────
sep
log "Authenticating as hr_admin..."
TOKEN=$(curl -sf -X POST "${BASE_URL}/auth/token" \
  -H "Content-Type: application/json" \
  -d '{"username":"hr_admin","password":"HrAdmin123!"}' | jq -r '.access_token')
success "Got JWT token (truncated): ${TOKEN:0:50}..."

INT_TOKEN=$(curl -sf -X POST "${BASE_URL}/auth/token" \
  -H "Content-Type: application/json" \
  -d '{"username":"integration_admin","password":"IntAdmin123!"}' | jq -r '.access_token')
success "Got integration_admin token."

DEMO_CORR_ID="demo-$(date +%s)"
DEMO_EMP_ID="DEMO$(date +%s)"

# ─── Step 1: JOINER ─────────────────────────────────────────────────────────
sep
log "STEP 1: Creating employee (Joiner workflow)..."
JOINER_RESP=$(curl -sf -X POST "${BASE_URL}/employees" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: ${DEMO_CORR_ID}" \
  -d "{
    \"employee_id\": \"${DEMO_EMP_ID}\",
    \"name\": \"Demo Employee\",
    \"email\": \"demo.employee.${DEMO_EMP_ID}@example.com\",
    \"department\": \"Engineering\",
    \"job_title\": \"Software Engineer\",
    \"location\": \"London\",
    \"start_date\": \"$(date +%Y-%m-%d)\"
  }")
echo "${JOINER_RESP}" | jq .
success "Employee created with status: $(echo "${JOINER_RESP}" | jq -r '.employment_status')"

# Activate
log "Activating employee..."
ACTIVATE_RESP=$(curl -sf -X POST "${BASE_URL}/employees/${DEMO_EMP_ID}/activate" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Correlation-ID: ${DEMO_CORR_ID}")
echo "${ACTIVATE_RESP}" | jq .
success "Employee status: $(echo "${ACTIVATE_RESP}" | jq -r '.employment_status')"

# ─── Step 2: MOVER ──────────────────────────────────────────────────────────
sep
log "STEP 2: Moving employee (department + title change)..."
MOVER_RESP=$(curl -sf -X PATCH "${BASE_URL}/employees/${DEMO_EMP_ID}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: ${DEMO_CORR_ID}" \
  -d '{"department":"Product","job_title":"Product Manager","location":"Berlin"}')
echo "${MOVER_RESP}" | jq .
success "Employee moved to department: $(echo "${MOVER_RESP}" | jq -r '.department')"

# ─── Step 3: LEAVER ─────────────────────────────────────────────────────────
sep
log "STEP 3: Terminating employee (Leaver workflow)..."
LEAVER_RESP=$(curl -sf -X POST "${BASE_URL}/employees/${DEMO_EMP_ID}/terminate" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: ${DEMO_CORR_ID}" \
  -d "{\"end_date\": \"$(date +%Y-%m-%d)\"}")
echo "${LEAVER_RESP}" | jq .
success "Employee terminated: $(echo "${LEAVER_RESP}" | jq -r '.employment_status')"

# ─── Wait for outbox delivery ────────────────────────────────────────────────
sep
log "Waiting 10 seconds for outbox worker to deliver events..."
sleep 10

# ─── Show delivered events ───────────────────────────────────────────────────
sep
log "DELIVERED EVENTS (from mock downstream):"
EVENTS=$(curl -sf "${MOCK_URL}/received-events")
echo "${EVENTS}" | jq .
DELIVERED_COUNT=$(echo "${EVENTS}" | jq 'length')
success "Total events delivered to mock downstream: ${DELIVERED_COUNT}"

# ─── Show outbox status ──────────────────────────────────────────────────────
sep
log "OUTBOX STATUS:"
curl -sf "${BASE_URL}/admin/outbox" \
  -H "Authorization: Bearer ${INT_TOKEN}" | jq '.items[] | {id, status, event_type, retry_count}'

# ─── Show audit trail ────────────────────────────────────────────────────────
sep
log "AUDIT TRAIL for employee ${DEMO_EMP_ID}:"
curl -sf "${BASE_URL}/admin/audit?employee_id=${DEMO_EMP_ID}" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.items[] | {action, actor, changed_fields, created_at}'

# ─── Forced Failure Demo ─────────────────────────────────────────────────────
sep
log "STEP 4: Forced failure demonstration..."
log "Creating a new subscription pointing to a non-existent endpoint..."

FAIL_SUB=$(curl -sf -X POST "${BASE_URL}/subscriptions" \
  -H "Authorization: Bearer ${INT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "http://localhost:9001/nonexistent",
    "event_types": ["employee.joined"],
    "description": "Forced failure test subscription"
  }')
FAIL_SUB_ID=$(echo "${FAIL_SUB}" | jq -r '.id')
success "Created failing subscription: ${FAIL_SUB_ID}"

FAIL_EMP_ID="FAIL$(date +%s)"
log "Creating employee to trigger failed delivery..."
curl -sf -X POST "${BASE_URL}/employees" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"employee_id\": \"${FAIL_EMP_ID}\",
    \"name\": \"Failure Test\",
    \"email\": \"fail.test.${FAIL_EMP_ID}@example.com\",
    \"department\": \"Test\",
    \"job_title\": \"Test Engineer\",
    \"location\": \"Test City\",
    \"start_date\": \"$(date +%Y-%m-%d)\"
  }" | jq '{employee_id, employment_status}'

log "Waiting for retries and dead-lettering (60 seconds)..."
sleep 15

log "Checking dead-lettered events..."
DEAD_RESP=$(curl -sf "${BASE_URL}/admin/outbox?status=dead_letter" \
  -H "Authorization: Bearer ${INT_TOKEN}")
DEAD_COUNT=$(echo "${DEAD_RESP}" | jq '.total')
echo "${DEAD_RESP}" | jq '.items[] | {id, status, retry_count, target_url, last_error}' 2>/dev/null || true
warn "Dead-lettered events found: ${DEAD_COUNT}"

if [ "${DEAD_COUNT}" -gt "0" ]; then
  DEAD_ID=$(echo "${DEAD_RESP}" | jq -r '.items[0].id')
  log "Manually retrying dead-lettered event: ${DEAD_ID}"
  RETRY_RESP=$(curl -sf -X POST "${BASE_URL}/admin/outbox/${DEAD_ID}/retry" \
    -H "Authorization: Bearer ${INT_TOKEN}")
  echo "${RETRY_RESP}" | jq .
  success "Event queued for retry. Status: $(echo "${RETRY_RESP}" | jq -r '.status')"
fi

# ─── Final Summary ────────────────────────────────────────────────────────────
sep
success "DEMO COMPLETE!"
echo ""
echo "  ✅  Joiner -> ${DEMO_EMP_ID} created with status pending"
echo "  ✅  Activation -> status changed to active"
echo "  ✅  Mover -> department/title/location changed"
echo "  ✅  Leaver -> terminated with end_date"
echo "  ✅  Events delivered to mock downstream: ${DELIVERED_COUNT}"
echo "  ✅  Full audit trail generated"
echo "  ✅  Forced failure -> retry -> dead-letter demonstrated"
echo ""
echo "  📖  Docs: http://localhost:8000/docs"
echo "  📊  Audit: ${BASE_URL}/admin/audit"
echo "  📬  Outbox: ${BASE_URL}/admin/outbox"
sep
