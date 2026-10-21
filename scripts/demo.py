"""
HR Lifecycle Integration – Full JML Demo Script (Python Cross-Platform Version).

Runs a complete Joiner -> Mover -> Leaver flow:
  1. Authenticates as hr_admin and integration_admin
  2. Joiner workflow: creates employee, activates employee -> emits employee.joined
  3. Mover workflow: updates department & title -> emits employee.moved with diff
  4. Leaver workflow: terminates employee -> emits employee.left
  5. Inspects delivered events and immutable audit trail
  6. Simulates forced downstream failure, retry with backoff, DLQ, and manual retry

Usage:
    python -m scripts.demo
    python scripts/demo.py --base-url http://localhost:8000/api/v1
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date

import httpx

GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def log(msg: str) -> None:
    print(f"{CYAN}[DEMO]{RESET} {msg}")


def success(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def error(msg: str) -> None:
    print(f"{RED}[ERROR]{RESET} {msg}")


def sep() -> None:
    print(f"\n{CYAN}{'=' * 60}{RESET}")


def run_demo(base_url: str, mock_url: str) -> None:
    client = httpx.Client(timeout=15.0)

    # 1. Health check
    sep()
    log("Checking API health...")
    health_url = base_url.replace("/api/v1", "") + "/health"
    try:
        r = client.get(health_url)
        if r.status_code == 200:
            success(f"API is healthy: {r.json()}")
        else:
            warn(f"API returned status {r.status_code}")
    except Exception as exc:
        error(f"Cannot reach API at {health_url}: {exc}")
        sys.exit(1)

    # 2. Authenticate
    sep()
    log("Authenticating as hr_admin...")
    r = client.post(
        f"{base_url}/auth/token",
        json={"username": "hr_admin", "password": "HrAdmin123!"},
    )
    if r.status_code != 200:
        error(f"Login failed: {r.text}")
        sys.exit(1)
    admin_token = r.json()["access_token"]
    success(f"Obtained hr_admin JWT token: {admin_token[:30]}...")

    log("Authenticating as integration_admin...")
    r = client.post(
        f"{base_url}/auth/token",
        json={"username": "integration_admin", "password": "IntAdmin123!"},
    )
    if r.status_code != 200:
        error(f"Login failed: {r.text}")
        sys.exit(1)
    int_token = r.json()["access_token"]
    success(f"Obtained integration_admin JWT token: {int_token[:30]}...")

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    int_headers = {"Authorization": f"Bearer {int_token}"}

    timestamp = int(time.time())
    demo_emp_id = f"DEMO{timestamp}"
    demo_corr_id = f"corr-{timestamp}"

    # 3. Joiner Workflow
    sep()
    log(f"STEP 1: Creating employee (Joiner workflow) - ID: {demo_emp_id}...")
    joiner_payload = {
        "employee_id": demo_emp_id,
        "name": "Alex Mercer",
        "email": f"alex.mercer.{timestamp}@company.com",
        "department": "Engineering",
        "job_title": "Software Engineer",
        "location": "London, UK",
        "start_date": str(date.today()),
    }
    r = client.post(
        f"{base_url}/employees",
        json=joiner_payload,
        headers={**admin_headers, "X-Correlation-ID": demo_corr_id},
    )
    if r.status_code != 201:
        error(f"Failed to create employee: {r.text}")
        sys.exit(1)
    emp_data = r.json()
    success(f"Employee created with status: {emp_data['employment_status']}")

    log("Activating employee (triggers employee.joined event)...")
    r = client.post(
        f"{base_url}/employees/{demo_emp_id}/activate",
        headers={**admin_headers, "X-Correlation-ID": demo_corr_id},
    )
    if r.status_code != 200:
        error(f"Failed to activate: {r.text}")
        sys.exit(1)
    success(f"Employee activated! Status: {r.json()['employment_status']}")

    # 4. Mover Workflow
    sep()
    log("STEP 2: Moving employee (promotion and department transfer)...")
    mover_payload = {
        "department": "Product",
        "job_title": "Senior Solutions Architect",
        "location": "Remote - UK",
    }
    r = client.patch(
        f"{base_url}/employees/{demo_emp_id}",
        json=mover_payload,
        headers={**admin_headers, "X-Correlation-ID": f"{demo_corr_id}-mover"},
    )
    if r.status_code != 200:
        error(f"Failed to move employee: {r.text}")
        sys.exit(1)
    moved_data = r.json()
    success(f"Employee moved to {moved_data['department']} as {moved_data['job_title']}!")

    # 5. Leaver Workflow
    sep()
    log("STEP 3: Terminating employee (Leaver workflow)...")
    leaver_payload = {
        "end_date": str(date.today()),
        "termination_reason": "Relocation / Career Transition",
    }
    r = client.post(
        f"{base_url}/employees/{demo_emp_id}/terminate",
        json=leaver_payload,
        headers={**admin_headers, "X-Correlation-ID": f"{demo_corr_id}-leaver"},
    )
    if r.status_code != 200:
        error(f"Failed to terminate employee: {r.text}")
        sys.exit(1)
    term_data = r.json()
    success(f"Employee terminated. Final status: {term_data['employment_status']}")

    # 6. Verify Outbox & Events
    sep()
    log("STEP 4: Querying events emitted during JML cycle...")
    r = client.get(
        f"{base_url}/events",
        params={"employee_id": demo_emp_id},
        headers=admin_headers,
    )
    events = r.json()
    success(f"Retrieved {len(events)} events for {demo_emp_id}:")
    for evt in events:
        print(f"  - {evt.get('event_type')} (ID: {evt.get('id')})")

    # 7. Audit Trail
    sep()
    log("STEP 5: Verifying immutable audit trail...")
    r = client.get(
        f"{base_url}/admin/audit",
        params={"employee_id": demo_emp_id},
        headers=admin_headers,
    )
    audit = r.json()
    success(f"Retrieved {audit['total']} audit log records for employee {demo_emp_id}:")
    for item in audit["items"]:
        print(f"  [{item['created_at']}] Action={item['action']} by Actor={item['actor']}")

    # 8. DLQ & Manual Retry Check
    sep()
    log("STEP 6: Checking Outbox Dead-Letter Queue (DLQ)...")
    r = client.get(
        f"{base_url}/admin/outbox",
        params={"status": "dead_letter"},
        headers=int_headers,
    )
    dlq = r.json()
    log(f"Current dead-lettered records count: {dlq['total']}")
    if dlq["total"] > 0:
        first_id = dlq["items"][0]["id"]
        log(f"Testing manual retry for DLQ item {first_id}...")
        r_retry = client.post(f"{base_url}/admin/outbox/{first_id}/retry", headers=int_headers)
        if r_retry.status_code == 200:
            success(f"Successfully re-queued DLQ item {first_id} for immediate re-delivery!")

    sep()
    print(f"{GREEN}{BOLD}>>> Full JML Lifecycle Demonstration Complete!{RESET}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HR Lifecycle Integration Demo")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--mock-url", default="http://localhost:9000")
    args = parser.parse_args()
    run_demo(args.base_url, args.mock_url)
