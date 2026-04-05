"""
GymAI – FastAPI Backend
========================
Endpoints:
  POST /chat          → main chatbot entry point
  GET  /calendar      → 7-day calendar with status colors
  GET  /day-plan      → detailed plan + log for one day
  POST /log           → direct activity log (non-chat)
  GET  /progress      → dashboard stats + motivational message
  POST /generate-plan → force regenerate the weekly plan
  GET  /health        → health check
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import google.genai.errors

load_dotenv()

import uuid
from passlib.context import CryptContext

from database import db
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


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield

app = FastAPI(
    title="GymAI – Multi-Agent Fitness Assistant",
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
async def chat(req: ChatRequest):
    """
    Primary chat endpoint. Routes to the right agent based on intent.
    Also persists conversation history in chat_history table.
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

    return ChatResponse(
        user_id=req.user_id,
        reply=result["reply"],
        intent=result.get("intent"),
        structured_data=result.get("structured_data"),
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
async def log_activity(req: LogRequest):
    """
    Direct (non-chat) activity logging.
    After saving the log, automatically triggers the Adjustment Agent.
    """
    from agents.adjustment_agent import AdjustmentAgent
    adj_agent = AdjustmentAgent()

    # Save the log via MCP tool
    result = await execute_tool("log_daily_activity", {
        "user_id": req.user_id,
        "date": req.date,
        "workout_done": req.workout_done,
        "food_items": req.food_items,
        "calories_consumed": req.calories,
        "notes": req.notes,
    })

    # Auto-trigger adjustment agent
    summary = (
        f"Workout: {'done' if req.workout_done else 'skipped'}. "
        f"Food: {', '.join(req.food_items) or 'not logged'}. "
        f"Calories: {req.calories}. Notes: {req.notes}"
    )
    adj_result = await adj_agent.run(
        summary,
        extra_context={"user_id": req.user_id, "log_date": req.date},
    )

    return {
        "success": True,
        "log_id": result.get("log_id"),
        "status": result.get("status_updated"),
        "adjustment_message": adj_result.get("reply", ""),
    }


@app.get("/progress", response_model=ProgressResponse)
async def get_progress(user_id: str = Query(...)):
    """Dashboard stats: consistency, weight change, motivational message."""
    summary = await execute_tool("get_progress_summary", {"user_id": user_id})
    profile = await db.get_user(user_id)
    logs = await db.get_recent_logs(user_id, days=7)

    # Get a motivational message from the Coach agent
    from agents.coach_agent import CoachAgent
    coach = CoachAgent()
    coach_result = await coach.run(
        "Give me a brief motivational update based on my progress.",
        extra_context={"user_id": user_id},
    )

    weight_change = await db.get_weight_change(user_id)

    return ProgressResponse(
        user_id=user_id,
        consistency_score=summary.get("consistency_score", 0.0),
        weight_change=weight_change,
        completed_days=summary.get("completed_days", 0),
        total_days=summary.get("total_logged_days", 0),
        motivational_message=coach_result.get("reply", "Keep going!"),
        recent_logs=[
            {
                "date": l["log_date"],
                "workout_done": bool(l["workout_done"]),
                "calories": l["calories_consumed"],
            }
            for l in logs
        ],
    )


@app.post("/generate-plan")
async def generate_plan(
    user_id: str = Query(...),
    week_start: Optional[str] = Query(None),
):
    """Force regenerate the weekly plan."""
    from agents.planner_agent import PlannerAgent
    planner = PlannerAgent()
    plan = await planner.generate_plan(user_id, week_start)
    if "error" in plan:
        raise HTTPException(400, plan["error"])
    return {"success": True, "plan": plan}

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

