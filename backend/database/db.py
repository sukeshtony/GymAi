"""
Google Cloud Firestore async database layer.
============================================
Drop-in replacement for the original SQLite (aiosqlite) module.
All function signatures and return shapes are identical so that
callers (tools.py, coordinator.py, main.py, etc.) need zero changes.

Collections
-----------
  users          – user profiles          (doc id = user_id)
  auth           – email/password records (doc id = user_id)
  user_state     – onboarding state       (doc id = user_id)
  weekly_plans   – 7-day plans            (auto id, queried by user_id)
  daily_logs     – per-day activity logs   (doc id = {user_id}_{log_date})
  adjustments    – AI-generated tweaks     (auto id)
  chat_history   – conversation turns      (auto id)
  weight_history – weight snapshots        (auto id)
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter

# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
_db: firestore.AsyncClient | None = None


def _get_db() -> firestore.AsyncClient:
    """Lazily initialise and return the Firestore AsyncClient."""
    global _db
    if _db is None:
        _db = firestore.AsyncClient(project=_PROJECT)
    return _db


async def init_db() -> None:
    """No-op — Firestore is schemaless. Kept for API compat with main.py."""
    _get_db()  # eagerly create the client so auth errors surface early


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    db = _get_db()
    doc = await db.collection("users").document(user_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["id"] = doc.id
    return data


async def upsert_user(user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    db = _get_db()
    now = datetime.utcnow().isoformat()
    doc_ref = db.collection("users").document(user_id)
    doc = await doc_ref.get()

    if doc.exists:
        existing = doc.to_dict()
    else:
        existing = {
            "id": user_id, "name": None, "goal": None, "weight": None,
            "height": None, "workout_start": None, "workout_end": None,
            "location": None, "diet_type": None, "food_access": None,
            "created_at": now, "updated_at": now,
        }

    existing.update(fields)
    existing["updated_at"] = now
    existing["id"] = user_id

    await doc_ref.set(existing)
    return existing


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def create_auth(user_id: str, email: str, password_hash: str) -> None:
    db = _get_db()
    now = datetime.utcnow().isoformat()
    await db.collection("auth").document(user_id).set({
        "user_id": user_id,
        "email": email,
        "password_hash": password_hash,
        "created_at": now,
    })


async def get_auth_by_email(email: str) -> Optional[Dict[str, Any]]:
    db = _get_db()
    query = (
        db.collection("auth")
        .where(filter=FieldFilter("email", "==", email))
        .limit(1)
    )
    result = None
    async for doc in query.stream():
        result = doc.to_dict()
        break
    return result


# ---------------------------------------------------------------------------
# User State
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
    "goal", "weight", "workout_start", "workout_end",
    "location", "diet_type", "food_access",
]


async def get_user_state(user_id: str) -> Dict[str, Any]:
    db = _get_db()
    doc = await db.collection("user_state").document(user_id).get()
    if doc.exists:
        data = doc.to_dict()
        # missing_fields is stored as a list natively in Firestore
        if isinstance(data.get("missing_fields"), str):
            import json
            data["missing_fields"] = json.loads(data["missing_fields"])
        return data
    # auto-create
    return await _create_user_state(user_id)


async def _create_user_state(user_id: str) -> Dict[str, Any]:
    db = _get_db()
    now = datetime.utcnow().isoformat()
    state = {
        "user_id": user_id,
        "missing_fields": REQUIRED_FIELDS,
        "onboarding_complete": 0,
        "current_step": "start",
        "updated_at": now,
    }
    await db.collection("user_state").document(user_id).set(state)
    return state


async def update_user_state(user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    state = await get_user_state(user_id)
    state.update(fields)
    state["updated_at"] = datetime.utcnow().isoformat()

    db = _get_db()
    await db.collection("user_state").document(user_id).set(state)
    return state


def _is_field_empty(value) -> bool:
    """Check if a profile field should be considered missing/empty."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    return False


async def recalculate_missing_fields(user_id: str) -> List[str]:
    user = await get_user(user_id) or {}
    missing = [f for f in REQUIRED_FIELDS if _is_field_empty(user.get(f))]
    state = await get_user_state(user_id)
    state["missing_fields"] = missing
    state["onboarding_complete"] = 1 if not missing else 0
    await update_user_state(user_id, state)
    return missing


# ---------------------------------------------------------------------------
# Weekly Plans
# ---------------------------------------------------------------------------

async def save_weekly_plan(user_id: str, week_start: str, plan_data: Dict) -> str:
    """Save a new weekly plan. Returns the Firestore document ID (str)."""
    db = _get_db()
    now = datetime.utcnow().isoformat()
    _ts, doc_ref = await db.collection("weekly_plans").add({
        "user_id": user_id,
        "week_start": week_start,
        "plan_data": plan_data,
        "created_at": now,
    })
    return doc_ref.id


async def get_weekly_plan(
    user_id: str, week_start: Optional[str] = None
) -> Optional[Dict]:
    db = _get_db()
    query = db.collection("weekly_plans").where(
        filter=FieldFilter("user_id", "==", user_id)
    )
    if week_start:
        query = query.where(
            filter=FieldFilter("week_start", "==", week_start)
        )
    query = query.order_by("created_at", direction=firestore.Query.DESCENDING).limit(1)

    async for doc in query.stream():
        data = doc.to_dict()
        data["_doc_id"] = doc.id
        # plan_data is stored as a native dict/list in Firestore — no JSON parse needed
        return data

    return None


async def update_day_plan(
    user_id: str, week_start: str, day_index: int, day_data: Dict
) -> bool:
    plan = await get_weekly_plan(user_id, week_start)
    if not plan:
        return False

    plan["plan_data"]["days"][day_index] = day_data

    db = _get_db()
    await db.collection("weekly_plans").document(plan["_doc_id"]).update({
        "plan_data": plan["plan_data"],
    })
    return True


# ---------------------------------------------------------------------------
# Daily Logs
# ---------------------------------------------------------------------------

def _log_doc_id(user_id: str, log_date: str) -> str:
    """Deterministic doc ID for upsert."""
    return f"{user_id}_{log_date}"


async def log_daily_activity(
    user_id: str,
    log_date: str,
    workout_done: bool,
    food_intake: List[str],
    calories_consumed: int,
    notes: str = "",
) -> str:
    """Upsert a daily log. Returns the document ID (str)."""
    db = _get_db()
    now = datetime.utcnow().isoformat()
    doc_id = _log_doc_id(user_id, log_date)
    doc_ref = db.collection("daily_logs").document(doc_id)

    doc = await doc_ref.get()
    if doc.exists:
        # update
        await doc_ref.update({
            "workout_done": int(workout_done),
            "food_intake": food_intake,
            "calories_consumed": calories_consumed,
            "notes": notes,
        })
    else:
        await doc_ref.set({
            "user_id": user_id,
            "log_date": log_date,
            "workout_done": int(workout_done),
            "food_intake": food_intake,
            "calories_consumed": calories_consumed,
            "notes": notes,
            "created_at": now,
        })
    return doc_id


async def get_daily_log(user_id: str, log_date: str) -> Optional[Dict]:
    db = _get_db()
    doc_id = _log_doc_id(user_id, log_date)
    doc = await db.collection("daily_logs").document(doc_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["id"] = doc.id
    return data


async def get_recent_logs(user_id: str, days: int = 7) -> List[Dict]:
    db = _get_db()
    query = (
        db.collection("daily_logs")
        .where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("log_date", direction=firestore.Query.DESCENDING)
        .limit(days)
    )
    result = []
    async for doc in query.stream():
        data = doc.to_dict()
        data["id"] = doc.id
        result.append(data)
    return result


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------

async def save_adjustment(
    user_id: str, adjustment_date: str, reason: str, changes: Dict
) -> str:
    """Save an adjustment record. Returns the Firestore document ID (str)."""
    db = _get_db()
    now = datetime.utcnow().isoformat()
    _ts, doc_ref = await db.collection("adjustments").add({
        "user_id": user_id,
        "adjustment_date": adjustment_date,
        "reason": reason,
        "changes": changes,
        "created_at": now,
    })
    return doc_ref.id


async def get_adjustments(user_id: str, target_date: str) -> List[Dict]:
    db = _get_db()
    query = (
        db.collection("adjustments")
        .where(filter=FieldFilter("user_id", "==", user_id))
        .where(filter=FieldFilter("adjustment_date", "==", target_date))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
    )
    result = []
    async for doc in query.stream():
        data = doc.to_dict()
        data["id"] = doc.id
        result.append(data)
    return result


# ---------------------------------------------------------------------------
# Chat History
# ---------------------------------------------------------------------------

async def append_chat(user_id: str, role: str, content: str) -> None:
    db = _get_db()
    now = datetime.utcnow().isoformat()
    await db.collection("chat_history").add({
        "user_id": user_id,
        "role": role,
        "content": content,
        "created_at": now,
    })


async def get_chat_history(user_id: str, limit: int = 20) -> List[Dict[str, str]]:
    db = _get_db()
    query = (
        db.collection("chat_history")
        .where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    rows: List[Dict[str, str]] = []
    async for doc in query.stream():
        d = doc.to_dict()
        rows.append({"role": d["role"], "content": d["content"]})
    rows.reverse()  # oldest first
    return rows


# ---------------------------------------------------------------------------
# Weight History
# ---------------------------------------------------------------------------

async def record_weight(user_id: str, weight: float) -> None:
    db = _get_db()
    now = datetime.utcnow().isoformat()
    await db.collection("weight_history").add({
        "user_id": user_id,
        "weight": weight,
        "recorded_at": now,
    })


async def get_weight_change(user_id: str) -> Optional[float]:
    """
    Returns current_weight - first_recorded_weight.
    Returns None if fewer than 2 snapshots exist.
    """
    db = _get_db()
    col = db.collection("weight_history")

    # First recorded weight (ASC)
    first_query = (
        col.where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("recorded_at", direction=firestore.Query.ASCENDING)
        .limit(1)
    )
    first_w = None
    async for doc in first_query.stream():
        first_w = doc.to_dict()["weight"]

    # Last recorded weight (DESC)
    last_query = (
        col.where(filter=FieldFilter("user_id", "==", user_id))
        .order_by("recorded_at", direction=firestore.Query.DESCENDING)
        .limit(1)
    )
    last_w = None
    async for doc in last_query.stream():
        last_w = doc.to_dict()["weight"]

    if first_w is None or last_w is None:
        return None

    # Check if there are at least 2 entries
    if first_w == last_w:
        count = 0
        count_query = col.where(filter=FieldFilter("user_id", "==", user_id)).limit(2)
        async for _ in count_query.stream():
            count += 1
        if count < 2:
            return None

    return round(last_w - first_w, 1)
