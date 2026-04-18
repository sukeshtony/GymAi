"""
FitnessAI – FastAPI Backend
========================
Endpoints:
  POST /chat          → main chatbot entry point
  GET  /calendar      → 7-day calendar with status colors
  GET  /day-plan      → detailed plan + log for one day
  POST /log           → direct activity log (non-chat)
  GET  /progress      → dashboard stats + motivational message
  POST /generate-plan → force regenerate the weekly plan
  GET  /task-status   → poll background task completion
  GET  /health        → health check
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import google.genai.errors

load_dotenv()

import uuid
from passlib.context import CryptContext

from database import db
import task_manager
from agents.coordinator import CoordinatorAgent
from mcp_tools.tools import execute_tool
from models.schemas import (
    ChatRequest, ChatResponse,
    CalendarResponse, CalendarDay,
    DayDetailResponse, DailyLogResponse,
    AdjustmentRecord, ProgressResponse,
    LogRequest,
    RegisterRequest, LoginRequest, AuthResponse
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Simple in-memory cache for motivational messages  {user_id: (message, timestamp)}
_motivation_cache: Dict[str, Tuple[str, float]] = {}
_MOTIVATION_CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield

app = FastAPI(
    title="FitnessAI – Multi-Agent Fitness Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend static files will be mounted at the bottom of this file

coordinator = CoordinatorAgent()

@app.exception_handler(google.genai.errors.APIError)
async def genai_api_error_handler(request: Request, exc: google.genai.errors.APIError):
    logger.error(f"GenAI API Error: {exc}")
    return JSONResponse(
        status_code=503,
        content={"detail": "The AI is currently experiencing very high demand. Please try logging your activity again in a few minutes."}
    )

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest):
    logger.info("STEP 1: Request received")
    print("STEP 1: Request received")
    logger.info("STEP 2: Checking existing user")
    existing = await db.get_auth_by_email(req.email)

    logger.info("STEP 3: Existing check done")

    if existing:
        logger.warning("STEP 3.1: Email already exists")
        raise HTTPException(400, "Email already registered")
    
    logger.info("STEP 4: Generating user_id")
    user_id = "user_" + uuid.uuid4().hex[:8]

    logger.info("STEP 5: Hashing password")
    hashed_pwd = pwd_context.hash(req.password)

    logger.info("STEP 6: BEFORE DB create_auth")
    await db.create_auth(user_id, req.email, hashed_pwd)

    logger.info("STEP 7: AFTER DB create_auth")

    logger.info("STEP 8: BEFORE DB upsert_user")
    await db.upsert_user(user_id, {"name": req.name})

    logger.info("STEP 9: AFTER DB upsert_user")

    logger.info("STEP 10: Returning response")

    return AuthResponse(
        user_id=user_id,
        email=req.email,
        name=req.name
    )

@app.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    auth_record = await db.get_auth_by_email(req.email)
    if not auth_record or not pwd_context.verify(req.password, auth_record["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    
    user_id = auth_record["user_id"]
    user_profile = await db.get_user(user_id)
    
    return AuthResponse(
        user_id=user_id,
        email=req.email,
        name=user_profile.get("name") if user_profile else None
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, background_tasks: BackgroundTasks):
    """
    Primary chat endpoint. Routes to the right agent based on intent.
    Also persists conversation history in chat_history table.

    If the coordinator signals a background_task, we spawn it via
    BackgroundTasks and return an instant response with a task_id
    for the frontend to poll.
    """
    if not req.user_id or not req.message.strip():
        raise HTTPException(400, "user_id and message are required")

    # Load recent history for context
    history = await db.get_chat_history(req.user_id, limit=10)

    # Run coordinator
    result = await coordinator.handle(req.user_id, req.message, history)

    # Persist both turns
    await db.append_chat(req.user_id, "user", req.message)
    await db.append_chat(req.user_id, "assistant", result["reply"])

    # Check if coordinator signaled a background task
    bg_task_type = result.get("background_task")
    structured = result.get("structured_data", {})

    if bg_task_type == "plan_generation":
        task_id = await task_manager.create_task(
            req.user_id, "plan_generation",
            metadata={"triggered_by": "chat"},
        )
        structured["pending_task"] = {
            "task_id": task_id,
            "type": "plan_generation",
            "message": "Generating your personalized 7-day plan...",
        }
        background_tasks.add_task(
            _bg_generate_plan, req.user_id, task_id
        )

    return ChatResponse(
        user_id=req.user_id,
        reply=result["reply"],
        intent=result.get("intent"),
        structured_data=structured,
    )


async def _bg_generate_plan(user_id: str, task_id: str) -> None:
    """Background task: generate a weekly plan and update task status."""
    try:
        from agents.planner_agent import PlannerAgent
        planner = PlannerAgent()
        plan = await planner.generate_plan(user_id)

        if "error" in plan:
            await task_manager.update_task(
                task_id, "failed",
                message=plan["error"],
            )
        else:
            await task_manager.update_task(
                task_id, "completed",
                message="Your 7-day fitness plan is ready! 🎉 Check the calendar tab.",
                result={"plan_generated": True},
            )
            # Also persist a chat message so the user sees it
            await db.append_chat(
                user_id, "assistant",
                "🗓️ Your personalized 7-day plan has been generated! "
                "Check the calendar tab to see your full week."
            )
    except Exception as e:
        logger.error(f"Background plan generation failed for {user_id}: {e}")
        await task_manager.update_task(
            task_id, "failed",
            message="Plan generation failed. Please try again.",
        )


async def _bg_run_adjustment(
    user_id: str, task_id: str, summary: str, log_date: str
) -> None:
    """Background task: run adjustment agent after activity logging."""
    try:
        from agents.adjustment_agent import AdjustmentAgent
        adj_agent = AdjustmentAgent()
        adj_result = await adj_agent.run(
            summary,
            extra_context={"user_id": user_id, "log_date": log_date},
        )
        reply = adj_result.get("reply", "")
        await task_manager.update_task(
            task_id, "completed",
            message=reply or "Plan adjusted based on your activity.",
            result={"adjustment_message": reply},
        )
        if reply:
            await db.append_chat(user_id, "assistant", f"⚡ {reply}")
    except Exception as e:
        logger.error(f"Background adjustment failed for {user_id}: {e}")
        await task_manager.update_task(
            task_id, "failed",
            message="Adjustment analysis failed.",
        )

@app.get("/health")
async def health():
    logger.info("HEALTH CHECK HIT")
    return {"status": "ok", "version": "1.0.0"}

@app.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    user_id: str = Query(...),
    week_start: Optional[str] = Query(None),
):
    """Returns the 7-day calendar with color-coded status for the frontend."""
    if not week_start:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.isoformat()

    plan = await db.get_weekly_plan(user_id, week_start)
    if not plan:
        raise HTTPException(404, "No plan found for this week. Use /chat to generate one.")

    days_data = plan["plan_data"].get("days", [])
    calendar_days = []
    for day in days_data:
        calendar_days.append(CalendarDay(
            date=day["date"],
            day_label=day["day_label"],
            status=day.get("status", "pending"),
            workout_type=day["workout_type"],
            total_calories=day["total_calories"],
        ))

    return CalendarResponse(
        user_id=user_id,
        week_start=week_start,
        days=calendar_days,
    )


@app.get("/day-plan", response_model=DayDetailResponse)
async def get_day_plan(
    user_id: str = Query(...),
    date_str: str = Query(..., alias="date"),
):
    """Returns full detail for a specific date: workout, meals, log, adjustments."""
    plan = await db.get_weekly_plan(user_id)
    day_plan_data = None
    if plan:
        for day in plan["plan_data"].get("days", []):
            if day["date"] == date_str:
                day_plan_data = day
                break

    log_row = await db.get_daily_log(user_id, date_str)
    log = None
    if log_row:
        log = DailyLogResponse(
            id=log_row["id"],
            user_id=user_id,
            log_date=log_row["log_date"],
            workout_done=bool(log_row["workout_done"]),
            food_intake=log_row["food_intake"],
            calories_consumed=log_row["calories_consumed"],
            notes=log_row.get("notes", ""),
        )

    adj_rows = await db.get_adjustments(user_id, date_str)
    adjustments = [
        AdjustmentRecord(
            user_id=user_id,
            adjustment_date=a["adjustment_date"],
            reason=a["reason"],
            changes=a["changes"],
        )
        for a in adj_rows
    ]

    if not day_plan_data and not log:
        raise HTTPException(404, f"No data found for {date_str}")

    return DayDetailResponse(
        date=date_str,
        day_plan=day_plan_data,
        log=log,
        adjustments=adjustments,
    )


@app.post("/log")
async def log_activity(req: LogRequest, background_tasks: BackgroundTasks):
    """
    Direct (non-chat) activity logging.
    Saves the log immediately (fast) and triggers the Adjustment Agent
    in the background so the user gets instant feedback.
    """
    # Save the log via MCP tool — this is fast (DB only)
    result = await execute_tool("log_daily_activity", {
        "user_id": req.user_id,
        "date": req.date,
        "workout_done": req.workout_done,
        "food_items": req.food_items,
        "calories_consumed": req.calories,
        "notes": req.notes,
    })

    # Kick off adjustment agent in background
    summary = (
        f"Workout: {'done' if req.workout_done else 'skipped'}. "
        f"Food: {', '.join(req.food_items) or 'not logged'}. "
        f"Calories: {req.calories}. Notes: {req.notes}"
    )
    task_id = await task_manager.create_task(
        req.user_id, "adjustment",
        metadata={"log_date": req.date},
    )
    background_tasks.add_task(
        _bg_run_adjustment, req.user_id, task_id, summary, req.date
    )

    return {
        "success": True,
        "log_id": result.get("log_id"),
        "status": result.get("status_updated"),
        "adjustment_message": "Activity logged! ✅ Analyzing and adjusting your plan...",
        "pending_task": {
            "task_id": task_id,
            "type": "adjustment",
        },
    }


@app.get("/progress", response_model=ProgressResponse)
async def get_progress(
    user_id: str = Query(...),
    background_tasks: BackgroundTasks = None,
):
    """Dashboard stats: consistency, weight change, motivational message.

    Uses a 5-minute cache for the CoachAgent motivational message
    so the dashboard loads instantly.
    """
    summary = await execute_tool("get_progress_summary", {"user_id": user_id})
    profile = await db.get_user(user_id)
    logs = await db.get_recent_logs(user_id, days=7)
    weight_change = await db.get_weight_change(user_id)

    # Use cached motivational message if available and fresh
    cached = _motivation_cache.get(user_id)
    if cached and (time.time() - cached[1]) < _MOTIVATION_CACHE_TTL:
        motivation_msg = cached[0]
    else:
        # Return a quick default and refresh in background
        motivation_msg = cached[0] if cached else "Keep pushing toward your goals! 💪"
        if background_tasks:
            background_tasks.add_task(_bg_refresh_motivation, user_id)

    return ProgressResponse(
        user_id=user_id,
        consistency_score=summary.get("consistency_score", 0.0),
        weight_change=weight_change,
        completed_days=summary.get("completed_days", 0),
        total_days=summary.get("total_logged_days", 0),
        motivational_message=motivation_msg,
        recent_logs=[
            {
                "date": l["log_date"],
                "workout_done": bool(l["workout_done"]),
                "calories": l["calories_consumed"],
            }
            for l in logs
        ],
    )


async def _bg_refresh_motivation(user_id: str) -> None:
    """Background task: refresh the cached motivational message."""
    try:
        from agents.coach_agent import CoachAgent
        coach = CoachAgent()
        coach_result = await coach.run(
            "Give me a brief motivational update based on my progress.",
            extra_context={"user_id": user_id},
        )
        msg = coach_result.get("reply", "Keep going!")
        _motivation_cache[user_id] = (msg, time.time())
    except Exception as e:
        logger.error(f"Background motivation refresh failed for {user_id}: {e}")


@app.post("/generate-plan")
async def generate_plan(
    user_id: str = Query(...),
    week_start: Optional[str] = Query(None),
    background_tasks: BackgroundTasks = None,
):
    """Force regenerate the weekly plan in the background."""
    task_id = await task_manager.create_task(
        user_id, "plan_generation",
        metadata={"triggered_by": "generate_plan_endpoint", "week_start": week_start},
    )
    background_tasks.add_task(_bg_generate_plan, user_id, task_id)
    return {
        "success": True,
        "message": "Plan generation started! Check back in ~30 seconds.",
        "pending_task": {
            "task_id": task_id,
            "type": "plan_generation",
        },
    }


@app.get("/task-status")
async def get_task_status(task_id: str = Query(...)):
    """Poll the status of a background task (plan generation, adjustment, etc.)."""
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "message": task.get("message", ""),
        "result": task.get("result"),
        "task_type": task.get("task_type"),
    }

# ---------------------------------------------------------------------------
# Mount Frontend (Must be last to not override API routes)
# ---------------------------------------------------------------------------
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

