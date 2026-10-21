"""
Mock Downstream Service – simulates payroll and IT access systems.

Features:
- Receives webhook events from the outbox worker
- Randomly fails ~30% of requests (configurable via MOCK_FAILURE_RATE env var)
- Supports X-Force-Failure header for deterministic testing
- Verifies HMAC-SHA256 signatures
- Stores received events in-memory for inspection
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Header, Request, status
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

MOCK_FAILURE_RATE = float(os.getenv("MOCK_FAILURE_RATE", "0.3"))
WEBHOOK_HMAC_SECRET = os.getenv("WEBHOOK_HMAC_SECRET", "changeme-webhook-hmac-secret")
MOCK_DOWNSTREAM_PORT = int(os.getenv("MOCK_DOWNSTREAM_PORT", "9000"))

app = FastAPI(
    title="Mock Downstream Service",
    description="Simulates payroll and IT access downstream systems.",
    version="1.0.0",
)

# In-memory store for received events (for test inspection)
_received_events: list[dict[str, Any]] = []


def _verify_signature(body: bytes, signature_header: str) -> bool:
    """Verify HMAC-SHA256 signature from X-HR-Signature header."""
    if not signature_header.startswith("sha256="):
        return False
    received_sig = signature_header[len("sha256="):]
    expected_sig = hmac.new(
        WEBHOOK_HMAC_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_sig, received_sig)


@app.post(
    "/webhook/payroll",
    summary="Payroll webhook receiver",
)
async def receive_payroll_webhook(
    request: Request,
    x_hr_signature: str = Header(default=""),
    x_hr_event_type: str = Header(default=""),
    x_hr_idempotency_key: str = Header(default=""),
    x_force_failure: str = Header(default="false"),
    x_correlation_id: str = Header(default=""),
) -> JSONResponse:
    return await _handle_webhook(
        request=request,
        system="payroll",
        signature=x_hr_signature,
        event_type=x_hr_event_type,
        idempotency_key=x_hr_idempotency_key,
        force_failure=x_force_failure.lower() == "true",
        correlation_id=x_correlation_id,
    )


@app.post(
    "/webhook/it-access",
    summary="IT Access webhook receiver",
)
async def receive_it_access_webhook(
    request: Request,
    x_hr_signature: str = Header(default=""),
    x_hr_event_type: str = Header(default=""),
    x_hr_idempotency_key: str = Header(default=""),
    x_force_failure: str = Header(default="false"),
    x_correlation_id: str = Header(default=""),
) -> JSONResponse:
    return await _handle_webhook(
        request=request,
        system="it_access",
        signature=x_hr_signature,
        event_type=x_hr_event_type,
        idempotency_key=x_hr_idempotency_key,
        force_failure=x_force_failure.lower() == "true",
        correlation_id=x_correlation_id,
    )


async def _handle_webhook(
    *,
    request: Request,
    system: str,
    signature: str,
    event_type: str,
    idempotency_key: str,
    force_failure: bool,
    correlation_id: str,
) -> JSONResponse:
    body = await request.body()

    # Verify HMAC signature
    if signature and not _verify_signature(body, signature):
        logger.warning(
            "Invalid signature for system=%s idempotency_key=%s", system, idempotency_key
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid HMAC signature"},
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid JSON body"},
        )

    # Forced failure for testing
    if force_failure:
        logger.warning(
            "Forced failure triggered for system=%s idempotency_key=%s", system, idempotency_key
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "Forced failure for testing"},
        )

    # Random failure simulation
    if random.random() < MOCK_FAILURE_RATE:
        logger.warning(
            "Random failure for system=%s idempotency_key=%s", system, idempotency_key
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"error": "Simulated downstream failure"},
        )

    # Success – store event
    received = {
        "system": system,
        "event_type": event_type,
        "idempotency_key": idempotency_key,
        "correlation_id": correlation_id,
        "payload": payload,
        "received_at": datetime.utcnow().isoformat(),
    }
    _received_events.append(received)
    logger.info(
        "Event received: system=%s event_type=%s idempotency_key=%s",
        system,
        event_type,
        idempotency_key,
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "accepted", "system": system, "idempotency_key": idempotency_key},
    )


@app.get("/received-events", summary="List all received events (for testing)")
async def get_received_events() -> list[dict[str, Any]]:
    """Return all events received by this mock service."""
    return _received_events


@app.delete("/received-events", summary="Clear received events (for testing)")
async def clear_received_events() -> dict:
    """Clear the in-memory events store."""
    _received_events.clear()
    return {"cleared": True}


@app.get("/health", summary="Health check")
async def health() -> dict:
    return {"status": "ok", "service": "mock-downstream"}
