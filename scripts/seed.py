"""
Idempotent seed script – generates ~50 synthetic employees and sample events.

Usage:
    python -m scripts.seed
    # or from docker: docker-compose exec api python -m scripts.seed
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import timedelta

from faker import Faker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/hrdb")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "hrdb")
SEED_EMPLOYEE_COUNT = int(os.getenv("SEED_EMPLOYEE_COUNT", "50"))
SEED_RANDOM_SEED = int(os.getenv("SEED_RANDOM_SEED", "42"))

fake = Faker()
Faker.seed(SEED_RANDOM_SEED)
random.seed(SEED_RANDOM_SEED)

DEPARTMENTS = [
    "Engineering", "Product", "Design", "Finance", "Legal",
    "Marketing", "Sales", "HR", "Operations", "Customer Success",
]

LOCATIONS = [
    "London", "New York", "Berlin", "Singapore", "Sydney",
    "Amsterdam", "Toronto", "Tokyo", "Bangalore", "Dublin",
]

JOB_TITLES = {
    "Engineering": ["Software Engineer", "Senior Engineer", "Staff Engineer", "Engineering Manager"],
    "Product": ["Product Manager", "Senior PM", "Director of Product", "APM"],
    "Design": ["UX Designer", "UI Designer", "Design Lead", "Product Designer"],
    "Finance": ["Financial Analyst", "Finance Manager", "CFO", "Accountant"],
    "Legal": ["Legal Counsel", "Paralegal", "General Counsel"],
    "Marketing": ["Marketing Manager", "Growth Manager", "Brand Manager", "CMO"],
    "Sales": ["Account Executive", "Sales Manager", "VP Sales", "SDR"],
    "HR": ["HR Business Partner", "Recruiter", "HR Manager", "CHRO"],
    "Operations": ["Operations Manager", "COO", "Process Analyst"],
    "Customer Success": ["Customer Success Manager", "CSM", "VP Customer Success"],
}

STATUSES = ["pending", "active", "active", "active", "on_leave", "terminated"]


async def seed(db):  # type: ignore[no-untyped-def]
    """Seed the database with synthetic employees."""
    from app.security.jwt_auth import hash_password

    logger.info("Starting seed with %d employees...", SEED_EMPLOYEE_COUNT)

    # ── Seed admin users ──────────────────────────────────────────────────────
    users = [
        {
            "_id": "user-admin-001",
            "username": "hr_admin",
            "hashed_password": hash_password("HrAdmin123!"),
            "role": "hr_admin",
            "active": True,
            "created_at": fake.date_time_this_year(),
        },
        {
            "_id": "user-viewer-001",
            "username": "hr_viewer",
            "hashed_password": hash_password("HrViewer123!"),
            "role": "hr_viewer",
            "active": True,
            "created_at": fake.date_time_this_year(),
        },
        {
            "_id": "user-integration-001",
            "username": "integration_admin",
            "hashed_password": hash_password("IntAdmin123!"),
            "role": "integration_admin",
            "active": True,
            "created_at": fake.date_time_this_year(),
        },
    ]
    for user in users:
        existing = await db.users.find_one({"username": user["username"]})
        if not existing:
            await db.users.insert_one(user)
            logger.info("Created user: %s (%s)", user["username"], user["role"])
        else:
            logger.info("User already exists: %s", user["username"])

    # ── Seed webhook subscriptions ────────────────────────────────────────────
    subscriptions = [
        {
            "_id": "sub-payroll-001",
            "target_url": f"{os.getenv('MOCK_DOWNSTREAM_URL', 'http://localhost:9000')}/webhook/payroll",
            "event_types": ["employee.joined", "employee.moved", "employee.left", "employee.status_changed"],
            "active": True,
            "description": "Payroll system – receives all HR events",
            "created_at": fake.date_time_this_year(),
            "updated_at": fake.date_time_this_year(),
        },
        {
            "_id": "sub-itaccess-001",
            "target_url": f"{os.getenv('MOCK_DOWNSTREAM_URL', 'http://localhost:9000')}/webhook/it-access",
            "event_types": ["employee.joined", "employee.left"],
            "active": True,
            "description": "IT Access system – provisions/de-provisions accounts",
            "created_at": fake.date_time_this_year(),
            "updated_at": fake.date_time_this_year(),
        },
    ]
    for sub in subscriptions:
        existing = await db.webhook_subscriptions.find_one({"_id": sub["_id"]})
        if not existing:
            await db.webhook_subscriptions.insert_one(sub)
            logger.info("Created subscription: %s -> %s", sub["_id"], sub["target_url"])
        else:
            logger.info("Subscription already exists: %s", sub["_id"])

    # ── Seed employees ────────────────────────────────────────────────────────
    manager_ids: list[str] = []  # will be filled as we create employees
    existing_emails: set[str] = set()
    existing_ids: set[str] = set()

    # Load existing
    async for doc in db.employees.find({}, {"employee_id": 1, "email": 1}):
        existing_ids.add(doc["employee_id"])
        existing_emails.add(doc["email"])

    created = 0
    for i in range(1, SEED_EMPLOYEE_COUNT + 1):
        emp_id = f"EMP{i:04d}"
        if emp_id in existing_ids:
            logger.debug("Employee %s already exists, skipping.", emp_id)
            continue

        department = random.choice(DEPARTMENTS)
        status = random.choice(STATUSES)
        start = fake.date_between(start_date="-5y", end_date="today")

        # Unique email
        attempts = 0
        while True:
            email = fake.company_email()
            if email not in existing_emails:
                existing_emails.add(email)
                break
            attempts += 1
            if attempts > 10:
                email = f"emp{i}.{fake.uuid4()[:8]}@example.com"
                existing_emails.add(email)
                break

        manager_id = random.choice(manager_ids) if manager_ids and random.random() > 0.3 else None

        doc = {
            "_id": f"uuid-{emp_id}",
            "employee_id": emp_id,
            "name": fake.name(),
            "email": email,
            "department": department,
            "job_title": random.choice(JOB_TITLES[department]),
            "manager_id": manager_id,
            "location": random.choice(LOCATIONS),
            "employment_status": status,
            "start_date": fake.date_time_between(start_date=start, end_date=start + timedelta(days=1)),
            "end_date": (
                fake.date_time_between(start_date="-1y", end_date="today")
                if status == "terminated"
                else None
            ),
            "created_at": fake.date_time_this_year(),
            "updated_at": fake.date_time_this_year(),
        }
        await db.employees.insert_one(doc)
        manager_ids.append(emp_id)
        created += 1

    logger.info(
        "Seed complete. Created %d/%d employees.", created, SEED_EMPLOYEE_COUNT
    )


async def main() -> None:
    from app.db import connect_db, disconnect_db, get_db

    await connect_db()
    db = get_db()
    try:
        await seed(db)
    finally:
        await disconnect_db()


if __name__ == "__main__":
    asyncio.run(main())
