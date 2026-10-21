# Operations & Troubleshooting Runbook

This runbook provides on-call engineers, DevOps, and integration specialists with diagnostic procedures and remediation workflows for the HR Lifecycle Integration Service.

---

## 1. Troubleshooting Guide (Symptom $\rightarrow$ Likely Cause $\rightarrow$ How to Verify $\rightarrow$ Fix)

### Scenario A: Webhook Delivery Failing

#### Symptom
Downstream systems (Payroll or IT Access) report that employee lifecycle events (e.g. `employee.joined`, `employee.moved`, `employee.left`) are not reflecting. Outbox entries show increasing attempt counts or error codes.

#### Likely Cause
1. Target downstream webhook endpoint is down, slow, or returning HTTP 5xx.
2. Network timeout / DNS resolution failure between the service worker and target endpoint.
3. Invalid or changed endpoint URL in the webhook subscription.
4. Payload rejection due to HMAC signature validation failure at the consumer end.

#### How to Verify
1. Query outbox status via Admin API:
   ```bash
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/admin/outbox?status=pending" | jq .
   ```
2. Inspect worker logs for connection timeouts or HTTP status codes:
   ```bash
   # Filter by target URL or outbox_id
   docker-compose logs --tail=100 -f api | grep "outbox_worker"
   ```
3. Test direct reachability of the downstream URL from inside the container:
   ```bash
   curl -I "http://mock_downstream:9000/health"
   ```
4. Verify the subscription URL and status:
   ```bash
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/admin/subscriptions" | jq .
   ```

#### Fix
1. **Downstream down/restarting**: Allow the outbox worker's exponential backoff to automatically retry. If downtime is prolonged, see [Dead-Lettered Events](#scenario-c-dead-lettered-events).
2. **Incorrect Subscription URL**: Update the subscription with the correct endpoint URL:
   ```bash
   curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"subscriber_name":"payroll","target_url":"http://mock_downstream:9000/webhooks/payroll","event_types":["employee.joined","employee.moved","employee.left"],"is_active":true}' \
     "http://localhost:8000/api/v1/admin/subscriptions"
   ```
3. **Secret Mismatch**: Verify that `WEBHOOK_HMAC_SECRET` matches across both the publisher and consumer environment variables.

---

### Scenario B: Events Stuck in Pending

#### Symptom
Events are created in the `events` table and outbox entries exist, but their `status` remains `"pending"` and `attempts` remains `0` indefinitely.

#### Likely Cause
1. The background outbox worker process is not running or crashed.
2. Worker polling loop is blocked or stalled waiting for a network socket without a timeout.
3. Database index corruption on `{status: 1, next_retry_at: 1}` preventing efficient query scans.
4. No active webhook subscriptions match the emitted `event_type`.

#### How to Verify
1. Check if worker process or container is active:
   ```bash
   ps aux | grep outbox_worker
   # or in docker:
   docker-compose ps
   ```
2. Verify outbox records:
   ```bash
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/admin/outbox?status=pending" | jq '.items[] | {id: .outbox_id, event_type: .event_type, created_at: .created_at, next_retry_at: .next_retry_at}'
   ```
3. Check if any active subscriptions match the event:
   ```bash
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/admin/subscriptions" | jq '.[] | select(.is_active == true)'
   ```

#### Fix
1. **Worker halted**: Restart the API or background worker container:
   ```bash
   docker-compose restart api
   ```
2. **Missing Subscription**: If an event type has no registered subscribers, the worker marks it or omits creating delivery jobs. Create an active subscription for the desired event types.
3. **System Clock Drift**: Ensure server clocks are synchronized with NTP if `next_retry_at` is set in the future.

---

### Scenario C: Dead-Lettered Events

#### Symptom
Outbox items reach maximum retry attempts (`attempts >= 5`) and transition to `status="dead_letter"`. Automated deliveries stop.

#### Likely Cause
1. Extended downstream outage exceeding maximum backoff window (~5 minutes).
2. Malformed payload or unhandled schema error in downstream parsing causing repeated HTTP 400 Bad Request responses.
3. Downstream authentication or authorization credentials expired.

#### How to Verify
1. Inspect dead-letter queue:
   ```bash
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/admin/outbox?status=dead_letter" | jq .
   ```
2. Check the `last_error` field on each dead-lettered record to identify the root cause:
   ```bash
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/admin/outbox?status=dead_letter" | jq '.items[] | {id: .outbox_id, error: .last_error, target: .target_url}'
   ```

#### Fix
1. Identify and resolve the underlying downstream issue.
2. Once the downstream is confirmed healthy, trigger manual replay via the Admin API:
   ```bash
   # Re-enqueue individual dead-letter item:
   curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/admin/outbox/{outbox_id}/retry"
   ```
3. Verify that status changes to `"pending"` and is subsequently delivered (`"delivered"`).

---

### Scenario D: Duplicate Events Detected Downstream

#### Symptom
Downstream systems report processing the same event multiple times (e.g. duplicate user account provisioning or double onboarding notifications).

#### Likely Cause
1. Downstream consumer successfully processed the event but responded slowly (> 10s timeout), causing the worker to assume failure and retry.
2. Downstream consumer does not implement idempotency checks on `X-Event-ID`.
3. Multiple outbox workers concurrently picking up the same unreserved outbox record.

#### How to Verify
1. Check the delivery logs for `X-Event-ID` in the outbox records:
   ```bash
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/admin/outbox?event_id={event_id}" | jq .
   ```
2. Check downstream HTTP response time logs.
3. Review worker logs to see if duplicate dispatches occurred.

#### Fix
1. **Consumer Idempotency**: Downstream subscribers must adhere to the integration contract: record `X-Event-ID` in an idempotent cache (e.g., Redis or DB unique index) and return HTTP 200 immediately for previously seen event IDs.
2. **Increase Timeout**: If the downstream service is legitimately slow, adjust `WEBHOOK_REQUEST_TIMEOUT_SECONDS` from 10s to a higher threshold in `.env`.
3. **Worker Locking**: Ensure atomic `find_one_and_update` status transitions are active in `outbox_service.py` to prevent race conditions across parallel worker instances.

---

### Scenario E: Authentication & 403 Forbidden Errors

#### Symptom
API clients or integration scripts receive HTTP 401 Unauthorized or HTTP 403 Forbidden when invoking endpoints.

#### Likely Cause
1. Expired JWT access token (default lifetime: 60 minutes).
2. Missing or malformed `Authorization: Bearer <token>` header.
3. User role does not have required permissions (e.g., `viewer` attempting `POST /api/v1/employees` or non-admin attempting `/api/v1/admin/subscriptions`).
4. Incorrect `JWT_SECRET_KEY` configured after container redeployment.

#### How to Verify
1. Decode the JWT token payload (e.g., using `jwt.io` or python-jose) to check expiry `exp` and `role`.
2. Inspect the current authenticated user identity:
   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/v1/auth/me" | jq .
   ```
3. Test against role requirements in the RBAC matrix (see [ARCHITECTURE.md](ARCHITECTURE.md)).

#### Fix
1. **Token Expired**: Obtain a fresh token:
   ```bash
   curl -X POST "http://localhost:8000/api/v1/auth/login" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=admin&password=adminpassword"
   ```
2. **Insufficient Permissions**: Assign the user an appropriate role (`hr_admin` or `hr_operator`) in MongoDB:
   ```javascript
   db.users.updateOne({ username: "john.doe" }, { $set: { role: "hr_admin" } });
   ```
3. **Secret Drift**: Ensure `JWT_SECRET_KEY` in `.env` is identical across all running API instances.

---

### Scenario F: MongoDB Connection Failure

#### Symptom
The API returns HTTP 500 or hangs during startup. Health checks (`/health` and `/ready`) return `503 Service Unavailable` with `database: disconnected`.

#### Likely Cause
1. MongoDB container or Atlas cluster is unreachable, paused, or network partitioned.
2. Connection string (`MONGODB_URI`) is invalid or has expired credentials.
3. Connection pool exhausted by unclosed client connections.
4. IP whitelist on MongoDB Atlas blocks the host IP address.

#### How to Verify
1. Check readiness endpoint:
   ```bash
   curl -i "http://localhost:8000/ready"
   ```
2. Test network socket connectivity to MongoDB:
   ```bash
   nc -zv localhost 27017
   ```
3. Inspect application startup logs:
   ```bash
   docker-compose logs api | grep -i "mongo"
   ```

#### Fix
1. **Local Docker Mongo Down**:
   ```bash
   docker-compose up -d mongo
   ```
2. **MongoDB Atlas IP Whitelist**: In MongoDB Atlas console -> Network Access -> Add current IP address or allow 0.0.0.0/0 for testing.
3. **Connection String Credentials**: Test connection directly via `mongosh`:
   ```bash
   mongosh "$MONGODB_URI"
   ```

---

## 2. Maintenance & Operational Procedures

### Procedure 1: Triggering Manual DLQ Replay
When a downstream outage is remediated, replay all dead-lettered messages:
```bash
# Get all dead letter IDs
DEAD_IDS=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/admin/outbox?status=dead_letter" | jq -r '.items[].outbox_id')

# Replay each
for id in $DEAD_IDS; do
  echo "Replaying $id..."
  curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
    "http://localhost:8000/api/v1/admin/outbox/$id/retry"
done
```

### Procedure 2: Rotating the Webhook HMAC Secret
To rotate `WEBHOOK_HMAC_SECRET` without dropping webhook delivery:
1. Coordinate with downstream subscribers to support dual-secret verification during the transition window.
2. Update `WEBHOOK_HMAC_SECRET` in `.env`.
3. Restart API and worker containers:
   ```bash
   docker-compose up -d --no-deps api
   ```
4. Verify signature validity on mock downstream or consumer verification logs.
