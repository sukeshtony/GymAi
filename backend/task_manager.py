"""
Background Task Manager
========================
Tracks the status of slow AI operations (plan generation, adjustment analysis)
so the frontend can poll for completion.

Statuses: pending → completed | failed

Collections used:
  background_tasks  – one doc per task (doc id = task_id)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from database import db as _db_module


def _get_db():
    """Reuse the Firestore client from the database module."""
    return _db_module._get_db()


COLLECTION = "background_tasks"


async def create_task(
    user_id: str,
    task_type: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a new background task record. Returns the task_id."""
    db = _get_db()
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()

    await db.collection(COLLECTION).document(task_id).set({
        "task_id": task_id,
        "user_id": user_id,
        "task_type": task_type,
        "status": "pending",
        "message": "Processing...",
        "result": None,
        "metadata": metadata or {},
        "created_at": now,
        "updated_at": now,
    })
    return task_id


async def update_task(
    task_id: str,
    status: str,
    message: str = "",
    result: Optional[Dict[str, Any]] = None,
) -> None:
    """Update a background task's status and optional result data."""
    db = _get_db()
    now = datetime.utcnow().isoformat()

    update_data: Dict[str, Any] = {
        "status": status,
        "updated_at": now,
    }
    if message:
        update_data["message"] = message
    if result is not None:
        update_data["result"] = result

    await db.collection(COLLECTION).document(task_id).update(update_data)


async def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a task's current status."""
    db = _get_db()
    doc = await db.collection(COLLECTION).document(task_id).get()
    if not doc.exists:
        return None
    return doc.to_dict()


async def get_latest_task_for_user(
    user_id: str, task_type: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get the most recent task for a user, optionally filtered by type."""
    from google.cloud.firestore_v1 import FieldFilter
    from google.cloud import firestore

    db = _get_db()
    query = db.collection(COLLECTION).where(
        filter=FieldFilter("user_id", "==", user_id)
    )
    if task_type:
        query = query.where(filter=FieldFilter("task_type", "==", task_type))

    query = query.order_by(
        "created_at", direction=firestore.Query.DESCENDING
    ).limit(1)

    async for doc in query.stream():
        return doc.to_dict()
    return None
