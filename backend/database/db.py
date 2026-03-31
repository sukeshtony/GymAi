"""
SQLite async database layer.
All collections mirror the Firestore schema described in the spec,
so swapping to Firestore later only requires changing this file.
"""
import json
import os
import aiosqlite
from datetime import datetime, date
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("DATABASE_PATH", "gym_ai.db")

# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    goal         TEXT,
    weight       REAL,
    height       REAL,
    workout_start TEXT,
    workout_end   TEXT,
    location     TEXT,
    diet_type    TEXT,
    food_access  TEXT,
    created_at   TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS user_state (
    user_id              TEXT PRIMARY KEY,
    missing_fields       TEXT DEFAULT '[]',
    onboarding_complete  INTEGER DEFAULT 0,
    current_step         TEXT DEFAULT 'start',
    updated_at           TEXT
);

CREATE TABLE IF NOT EXISTS weekly_plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    week_start  TEXT NOT NULL,
    plan_data   TEXT NOT NULL,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS daily_logs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    log_date          TEXT NOT NULL,
    workout_done      INTEGER DEFAULT 0,
    food_intake       TEXT DEFAULT '[]',
    calories_consumed INTEGER DEFAULT 0,
    notes             TEXT,
    created_at        TEXT
);

CREATE TABLE IF NOT EXISTS adjustments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT NOT NULL,
    adjustment_date  TEXT NOT NULL,
    reason           TEXT,
    changes          TEXT DEFAULT '{}',
    created_at       TEXT
);

CREATE TABLE IF NOT EXISTS chat_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def upsert_user(user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.utcnow().isoformat()
    existing = await get_user(user_id)
    if existing is None:
        existing = {
            "id": user_id, "name": None, "goal": None, "weight": None,
            "height": None, "workout_start": None, "workout_end": None,
            "location": None, "diet_type": None, "food_access": None,
            "created_at": now, "updated_at": now,
        }
    existing.update(fields)
    existing["updated_at"] = now
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO users
               (id, name, goal, weight, height, workout_start, workout_end,
                location, diet_type, food_access, created_at, updated_at)
               VALUES (:id,:name,:goal,:weight,:height,:workout_start,:workout_end,
                       :location,:diet_type,:food_access,:created_at,:updated_at)""",
            existing,
        )
        await db.commit()
    return existing


# ---------------------------------------------------------------------------
# User State
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ["goal", "weight", "workout_start", "workout_end",
                   "location", "diet_type", "food_access"]


async def get_user_state(user_id: str) -> Dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_state WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                d = dict(row)
                d["missing_fields"] = json.loads(d["missing_fields"])
                return d
    # auto-create
    return await _create_user_state(user_id)


async def _create_user_state(user_id: str) -> Dict[str, Any]:
    now = datetime.utcnow().isoformat()
    state = {
        "user_id": user_id,
        "missing_fields": REQUIRED_FIELDS,
        "onboarding_complete": 0,
        "current_step": "start",
        "updated_at": now,
    }
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO user_state
               (user_id, missing_fields, onboarding_complete, current_step, updated_at)
               VALUES (?,?,?,?,?)""",
            (user_id, json.dumps(REQUIRED_FIELDS), 0, "start", now),
        )
        await db.commit()
    return state


async def update_user_state(user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    state = await get_user_state(user_id)
    state.update(fields)
    state["updated_at"] = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO user_state
               (user_id, missing_fields, onboarding_complete, current_step, updated_at)
               VALUES (:user_id,:missing_fields,:onboarding_complete,:current_step,:updated_at)""",
            {**state, "missing_fields": json.dumps(state["missing_fields"])},
        )
        await db.commit()
    return state


async def recalculate_missing_fields(user_id: str) -> List[str]:
    user = await get_user(user_id) or {}
    missing = [f for f in REQUIRED_FIELDS if not user.get(f)]
    state = await get_user_state(user_id)
    state["missing_fields"] = missing
    state["onboarding_complete"] = 1 if not missing else 0
    await update_user_state(user_id, state)
    return missing


# ---------------------------------------------------------------------------
# Weekly Plans
# ---------------------------------------------------------------------------

async def save_weekly_plan(user_id: str, week_start: str, plan_data: Dict) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO weekly_plans (user_id, week_start, plan_data, created_at)
               VALUES (?,?,?,?)""",
            (user_id, week_start, json.dumps(plan_data), now),
        )
        await db.commit()
        return cur.lastrowid


async def get_weekly_plan(user_id: str, week_start: Optional[str] = None) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if week_start:
            async with db.execute(
                "SELECT * FROM weekly_plans WHERE user_id=? AND week_start=? ORDER BY id DESC LIMIT 1",
                (user_id, week_start),
            ) as cur:
                row = await cur.fetchone()
        else:
            async with db.execute(
                "SELECT * FROM weekly_plans WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["plan_data"] = json.loads(d["plan_data"])
        return d


async def update_day_plan(user_id: str, week_start: str, day_index: int, day_data: Dict) -> bool:
    plan = await get_weekly_plan(user_id, week_start)
    if not plan:
        return False
    plan["plan_data"]["days"][day_index] = day_data
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE weekly_plans SET plan_data=? WHERE user_id=? AND week_start=?",
            (json.dumps(plan["plan_data"]), user_id, week_start),
        )
        await db.commit()
    return True


# ---------------------------------------------------------------------------
# Daily Logs
# ---------------------------------------------------------------------------

async def log_daily_activity(
    user_id: str,
    log_date: str,
    workout_done: bool,
    food_intake: List[str],
    calories_consumed: int,
    notes: str = "",
) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # upsert by date
        async with db.execute(
            "SELECT id FROM daily_logs WHERE user_id=? AND log_date=?", (user_id, log_date)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            await db.execute(
                """UPDATE daily_logs SET workout_done=?,food_intake=?,
                   calories_consumed=?,notes=? WHERE user_id=? AND log_date=?""",
                (int(workout_done), json.dumps(food_intake), calories_consumed,
                 notes, user_id, log_date),
            )
            row_id = existing[0]
        else:
            cur = await db.execute(
                """INSERT INTO daily_logs
                   (user_id,log_date,workout_done,food_intake,calories_consumed,notes,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (user_id, log_date, int(workout_done), json.dumps(food_intake),
                 calories_consumed, notes, now),
            )
            row_id = cur.lastrowid
        await db.commit()
        return row_id


async def get_daily_log(user_id: str, log_date: str) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM daily_logs WHERE user_id=? AND log_date=?", (user_id, log_date)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["food_intake"] = json.loads(d["food_intake"])
            return d


async def get_recent_logs(user_id: str, days: int = 7) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM daily_logs WHERE user_id=? ORDER BY log_date DESC LIMIT ?",
            (user_id, days),
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["food_intake"] = json.loads(d["food_intake"])
                result.append(d)
            return result


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------

async def save_adjustment(
    user_id: str, adjustment_date: str, reason: str, changes: Dict
) -> int:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO adjustments (user_id, adjustment_date, reason, changes, created_at)
               VALUES (?,?,?,?,?)""",
            (user_id, adjustment_date, reason, json.dumps(changes), now),
        )
        await db.commit()
        return cur.lastrowid


async def get_adjustments(user_id: str, target_date: str) -> List[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM adjustments WHERE user_id=? AND adjustment_date=? ORDER BY id DESC",
            (user_id, target_date),
        ) as cur:
            rows = await cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["changes"] = json.loads(d["changes"])
                result.append(d)
            return result


# ---------------------------------------------------------------------------
# Chat History
# ---------------------------------------------------------------------------

async def append_chat(user_id: str, role: str, content: str) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
            (user_id, role, content, now),
        )
        await db.commit()


async def get_chat_history(user_id: str, limit: int = 20) -> List[Dict[str, str]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT role, content FROM chat_history
               WHERE user_id=? ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
