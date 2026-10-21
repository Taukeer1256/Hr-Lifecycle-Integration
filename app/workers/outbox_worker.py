"""
Outbox Worker – polls for pending outbox entries and delivers them to
registered webhook endpoints using HMAC-SHA256 signatures and exponential
backoff retry logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.db import get_db
from app.security.rbac import sign_payload
from app.services.outbox_service import (
    get_pending_outbox,
    mark_delivered,
    mark_failed,
)

logger = logging.getLogger(__name__)


def compute_next_attempt(retry_count: int, base: int, max_wait: int) -> datetime:
    """
    Exponential backoff: base^retry_count seconds, capped at max_wait.
    Adds a small jitter to avoid thundering herd.
    """
    wait = min(base**retry_count, max_wait)
    return datetime.utcnow() + timedelta(seconds=wait)


async def deliver_event(
    client: httpx.AsyncClient,
    outbox_doc: dict[str, Any],
    settings: Any,
) -> None:
    """Attempt delivery of a single outbox event to its target URL."""
    outbox_id = str(outbox_doc["_id"])
    target_url = outbox_doc["target_url"]
    payload = outbox_doc["payload"]
    retry_count: int = outbox_doc.get("retry_count", 0)
    max_retries: int = outbox_doc.get("max_retries", settings.outbox_max_retries)

    # Build signed payload
    signature = sign_payload(payload)
    headers = {
        "Content-Type": "application/json",
        "X-HR-Signature": f"sha256={signature}",
        "X-HR-Event-Type": outbox_doc["event_type"],
        "X-HR-Idempotency-Key": outbox_doc["idempotency_key"],
        "X-Correlation-ID": outbox_doc.get("correlation_id", ""),
    }

    db = get_db()
    logger.info(
        "Delivering outbox_id=%s to %s (attempt %d/%d)",
        outbox_id,
        target_url,
        retry_count + 1,
        max_retries,
    )

    try:
        response = await client.post(
            target_url,
            content=json.dumps(payload, default=str),
            headers=headers,
            timeout=settings.webhook_request_timeout_seconds,
        )
        if response.status_code < 300:
            await mark_delivered(db, outbox_id)
            logger.info("Delivered outbox_id=%s status=%d", outbox_id, response.status_code)
        else:
            error = f"HTTP {response.status_code}: {response.text[:200]}"
            is_dead = retry_count + 1 >= max_retries
            next_at = compute_next_attempt(
                retry_count + 1,
                settings.outbox_backoff_base_seconds,
                settings.outbox_backoff_max_seconds,
            )
            await mark_failed(db, outbox_id, error, next_at, dead_letter=is_dead)
            if is_dead:
                logger.error(
                    "Dead-lettered outbox_id=%s after %d retries. Error: %s",
                    outbox_id,
                    retry_count + 1,
                    error,
                )
            else:
                logger.warning(
                    "Delivery failed outbox_id=%s retry=%d error=%s next_at=%s",
                    outbox_id,
                    retry_count + 1,
                    error,
                    next_at,
                )
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        error = f"{type(exc).__name__}: {exc}"
        is_dead = retry_count + 1 >= max_retries
        next_at = compute_next_attempt(
            retry_count + 1,
            settings.outbox_backoff_base_seconds,
            settings.outbox_backoff_max_seconds,
        )
        await mark_failed(db, outbox_id, error, next_at, dead_letter=is_dead)
        if is_dead:
            logger.error(
                "Dead-lettered outbox_id=%s after %d retries. Error: %s",
                outbox_id,
                retry_count + 1,
                error,
            )
        else:
            logger.warning(
                "Network error outbox_id=%s retry=%d error=%s",
                outbox_id,
                retry_count + 1,
                error,
            )


async def run_outbox_worker() -> None:
    """Main outbox worker loop – polls and delivers pending events."""
    settings = get_settings()
    logger.info(
        "Outbox worker started. Poll interval: %ds",
        settings.outbox_poll_interval_seconds,
    )

    async with httpx.AsyncClient() as client:
        while True:
            try:
                pending = await get_pending_outbox(get_db())
                if pending:
                    logger.info("Processing %d pending outbox entries.", len(pending))
                    tasks = [
                        deliver_event(client, doc, settings) for doc in pending
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as exc:
                logger.error("Outbox worker error: %s", exc, exc_info=True)

            await asyncio.sleep(settings.outbox_poll_interval_seconds)
