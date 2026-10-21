# API Reference Manual

The **HR Lifecycle Integration Service** exposes a RESTful API versioned under `/api/v1`. Interactive OpenAPI/Swagger documentation is available at `/docs`, and ReDoc is hosted at `/redoc`.

---

## Global Headers & Authentication

All protected endpoints require an HTTP Bearer Token in the `Authorization` header:

```http
Authorization: Bearer <access_token>
```

### Request Correlation
Every incoming request supports the `X-Correlation-ID` header. If omitted, the server generates a UUIDv4 and returns it in the response headers. All downstream webhooks and audit logs inherit this correlation ID for distributed tracing.

```http
X-Correlation-ID: 7a932d18-5a41-4c12-8e6d-209a3978fb31
```

---

## 1. Authentication Endpoints

### 1.1 Login & Obtain Token
- **Method**: `POST`
- **Path**: `/api/v1/auth/login`
- **Access**: Public
- **Content-Type**: `application/x-www-form-urlencoded`

#### Request Parameters
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `username` | `string` | Yes | User login handle (e.g., `admin`, `operator`, `viewer`) |
| `password` | `string` | Yes | User password |

#### Response (`200 OK`)
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

---

### 1.2 Get Current User Identity
- **Method**: `GET`
- **Path**: `/api/v1/auth/me`
- **Access**: Authenticated (`hr_admin`, `hr_operator`, `viewer`, `integration_service`)

#### Response (`200 OK`)
```json
{
  "username": "admin",
  "email": "admin@company.com",
  "role": "hr_admin",
  "is_active": true
}
```

---

## 2. Employees & JML Lifecycle Endpoints

### 2.1 List Employees
- **Method**: `GET`
- **Path**: `/api/v1/employees`
- **Access**: `hr_admin`, `hr_operator`, `viewer`

#### Query Parameters
| Parameter | Type | Description |
| :--- | :--- | :--- |
| `department` | `string` | Filter by department name (e.g., `Engineering`) |
| `employment_status` | `string` | `pending`, `active`, `on_leave`, `terminated` |
| `search` | `string` | Substring match against name or email |
| `page` | `int` | Page number (default: `1`) |
| `page_size` | `int` | Items per page (default: `20`, max: `100`) |

#### Response (`200 OK`)
```json
{
  "items": [
    {
      "employee_id": "EMP-00042",
      "first_name": "Eleanor",
      "last_name": "Vance",
      "email": "eleanor.vance@company.com",
      "department": "Engineering",
      "job_title": "Senior Backend Engineer",
      "manager_id": "EMP-00010",
      "location": "San Francisco, CA",
      "employment_status": "active",
      "start_date": "2026-02-01T00:00:00Z",
      "end_date": null,
      "created_at": "2026-01-15T09:00:00Z",
      "updated_at": "2026-02-01T00:00:00Z"
    }
  ],
  "total": 52,
  "page": 1,
  "page_size": 20,
  "pages": 3
}
```

---

### 2.2 Create Employee (Joiner Workflow)
- **Method**: `POST`
- **Path**: `/api/v1/employees`
- **Access**: `hr_admin`, `hr_operator`
- **Status Code**: `201 Created`

#### Request Body
```json
{
  "employee_id": "EMP-00101",
  "first_name": "Lucas",
  "last_name": "Silva",
  "email": "lucas.silva@company.com",
  "department": "Product",
  "job_title": "Product Analyst",
  "manager_id": "EMP-00015",
  "location": "New York, NY",
  "start_date": "2026-11-01T00:00:00Z",
  "status": "pending"
}
```

*Note: Initial creation sets status to `pending`. When `start_date` arrives, trigger activation.*

---

### 2.3 Activate Employee
- **Method**: `POST`
- **Path**: `/api/v1/employees/{employee_id}/activate`
- **Access**: `hr_admin`, `hr_operator`

Transitions employee from `pending` to `active` and atomically emits the `employee.joined` outbox event.

#### Response (`200 OK`)
```json
{
  "employee_id": "EMP-00101",
  "first_name": "Lucas",
  "last_name": "Silva",
  "email": "lucas.silva@company.com",
  "department": "Product",
  "job_title": "Product Analyst",
  "employment_status": "active",
  "start_date": "2026-11-01T00:00:00Z",
  "updated_at": "2026-10-21T10:15:00Z"
}
```

---

### 2.4 Update Employee (Mover Workflow)
- **Method**: `PATCH`
- **Path**: `/api/v1/employees/{employee_id}`
- **Access**: `hr_admin`, `hr_operator`

Updates organizational attributes (department, title, manager, location, status) and emits `employee.moved` containing field-level diffs.

#### Request Body
```json
{
  "department": "Design",
  "job_title": "Senior UX Researcher",
  "location": "London, UK"
}
```

---

### 2.5 Terminate Employee (Leaver Workflow)
- **Method**: `POST`
- **Path**: `/api/v1/employees/{employee_id}/terminate`
- **Access**: `hr_admin`, `hr_operator`

Marks employee as `terminated`, sets `end_date`, and emits `employee.left`.

#### Request Body
```json
{
  "end_date": "2026-10-31T17:00:00Z",
  "termination_reason": "Voluntary Resignation"
}
```

---

## 3. Events & Subscriptions

### 3.1 List Events
- **Method**: `GET`
- **Path**: `/api/v1/events`
- **Query Params**: `event_type`, `employee_id`, `page`, `page_size`

### 3.2 Create Webhook Subscription
- **Method**: `POST`
- **Path**: `/api/v1/subscriptions`
- **Access**: `hr_admin`
- **Status Code**: `201 Created`

#### Request Body
```json
{
  "target_url": "http://mock_downstream:9000/webhooks/payroll",
  "event_types": ["employee.joined", "employee.moved", "employee.left"],
  "description": "Enterprise Payroll Webhook Listener"
}
```

---

## 4. Admin & Operational Controls

### 4.1 Query Outbox Records
- **Method**: `GET`
- **Path**: `/api/v1/admin/outbox`
- **Query Params**: `status` (`pending`, `delivered`, `dead_letter`), `employee_id`, `page`, `page_size`

### 4.2 Retry Failed Outbox Record
- **Method**: `POST`
- **Path**: `/api/v1/admin/outbox/{outbox_id}/retry`
- **Access**: `hr_admin`

Resets an individual dead-lettered event's attempt counter to 0 and marks status as `pending` for immediate re-delivery.

### 4.3 Retry All Dead-Lettered Records
- **Method**: `POST`
- **Path**: `/api/v1/admin/outbox/retry-all-dead-letters`
- **Access**: `hr_admin`

---

## 5. Webhook Delivery Specification & Verification

When an event triggers delivery, the outbox worker sends an HTTP POST request to registered subscriber URLs.

### HTTP Headers Sent to Subscribers
| Header | Description |
| :--- | :--- |
| `Content-Type` | `application/json` |
| `X-Signature-SHA256` | Hex-encoded HMAC-SHA256 signature calculated over the raw request body using `WEBHOOK_HMAC_SECRET` |
| `X-Event-ID` | Unique event UUID (used for downstream deduplication) |
| `X-Timestamp` | ISO 8601 UTC timestamp of dispatch |
| `X-Correlation-ID` | Trace identifier propagated from the triggering request |

### Python Webhook Signature Verification Example
```python
import hashlib
import hmac

def verify_webhook_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Validates the X-Signature-SHA256 header against the incoming payload.
    """
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature_header)
```
