"""MongoDB connection management."""

from __future__ import annotations

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, IndexModel

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None  # type: ignore[type-arg]
_db: Optional[AsyncIOMotorDatabase] = None  # type: ignore[type-arg]


async def connect_db() -> None:
    """Create MongoDB client and ensure indexes."""
    global _client, _db
    settings = get_settings()

    if getattr(settings, "use_mock_db", False) or settings.mongodb_uri.startswith("mongomock://"):
        try:
            import mongomock_motor

            logger.info("Using in-memory MongoDB (mongomock_motor)...")
            _client = mongomock_motor.AsyncMongoMockClient()  # type: ignore[assignment]
            _db = _client[settings.mongodb_db_name]  # type: ignore[assignment]
            await _ensure_indexes()
            return
        except ImportError:
            pass

    logger.info("Connecting to MongoDB at %s", settings.mongodb_uri)
    _client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=2000)
    _db = _client[settings.mongodb_db_name]
    # Verify connectivity
    try:
        await _client.admin.command("ping")
        logger.info("MongoDB connection established.")
    except Exception as exc:
        if settings.app_env != "production":
            try:
                import mongomock_motor

                logger.warning(
                    "Could not connect to MongoDB (%s). Falling back to in-memory mongomock for local development.",
                    exc,
                )
                _client = mongomock_motor.AsyncMongoMockClient()  # type: ignore[assignment]
                _db = _client[settings.mongodb_db_name]  # type: ignore[assignment]
                await _ensure_indexes()
                return
            except ImportError:
                pass
        logger.error("MongoDB connection failed: %s", exc)
        raise
    await _ensure_indexes()


async def disconnect_db() -> None:
    """Close the MongoDB client."""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed.")


def get_db() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    """Return the active database handle (raises if not connected)."""
    if _db is None:
        raise RuntimeError("Database is not initialised. Call connect_db() first.")
    return _db


async def _ensure_indexes() -> None:
    """Create all required MongoDB indexes."""
    db = get_db()

    # employees collection
    await db.employees.create_indexes(
        [
            IndexModel([("employee_id", ASCENDING)], unique=True),
            IndexModel([("email", ASCENDING)], unique=True),
            IndexModel([("department", ASCENDING)]),
            IndexModel([("employment_status", ASCENDING)]),
        ]
    )

    # outbox collection
    await db.outbox.create_indexes(
        [
            IndexModel([("status", ASCENDING), ("next_attempt_at", ASCENDING)]),
            IndexModel([("idempotency_key", ASCENDING)], unique=True),
        ]
    )

    # audit_log collection
    await db.audit_log.create_indexes(
        [
            IndexModel([("employee_id", ASCENDING)]),
            IndexModel([("actor", ASCENDING)]),
            IndexModel([("created_at", ASCENDING)]),
        ]
    )

    # webhook_subscriptions collection
    await db.webhook_subscriptions.create_indexes(
        [
            IndexModel([("event_type", ASCENDING)]),
            IndexModel([("active", ASCENDING)]),
        ]
    )

    # users collection
    await db.users.create_indexes(
        [
            IndexModel([("username", ASCENDING)], unique=True),
        ]
    )

    logger.info("MongoDB indexes ensured.")
