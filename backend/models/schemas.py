"""
Pydantic v2 schemas for all API request/response bodies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# User / Profile
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    id: str
    name: Optional[str] = None
    goal: Optional[str] = None          # "weight_loss" | "muscle_gain" | "maintenance"
    weight: Optional[float] = None      # kg
    height: Optional[float] = None      # cm
    workout_start: Optional[str] = None # "07:00"
    workout_end: Optional[str] = None   # "08:00"
    location: Optional[str] = None      # city name
    diet_type: Optional[str] = None     # "veg" | "non_veg" | "vegan"
    food_access: Optional[str] = None   # "home" | "hostel" | "outside"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class UserState(BaseModel):
    user_id: str
    missing_fields: List[str] = []
    onboarding_complete: bool = False
    current_step: str = "start"
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Plan structures
# ---------------------------------------------------------------------------

class Exercise(BaseModel):
    name: str
    sets: Optional[int] = None
    reps: Optional[str] = None       # "10-12" or "30 seconds"
    duration_min: Optional[int] = None
    notes: Optional[str] = None


class Meal(BaseModel):
    meal_type: str                    # breakfast / lunch / dinner / snack
    items: List[str]
    calories: int
    protein_g: Optional[int] = None
    notes: Optional[str] = None


class DayPlan(BaseModel):
    day_index: int                    # 0 = Monday
    date: str                         # ISO date
    day_label: str                    # "Monday"
    workout_type: str                 # "Push" / "Cardio" / "Rest" etc.
    workout_start: str
    workout_end: str
    exercises: List[Exercise]
    meals: List[Meal]
    total_calories: int
    water_ml: int = 2500
    status: str = "pending"           # pending / completed / missed / adjusted
    adjustment_note: Optional[str] = None


class WeeklyPlan(BaseModel):
    user_id: str
    week_start: str
    days: List[DayPlan]
    weekly_calories: int
    goal_summary: str


# ---------------------------------------------------------------------------
# Daily Log
# ---------------------------------------------------------------------------

class DailyLog(BaseModel):
    user_id: str
    log_date: str
    workout_done: bool
    food_intake: List[str] = []
    calories_consumed: int = 0
    notes: str = ""


class DailyLogResponse(DailyLog):
    id: int


# ---------------------------------------------------------------------------
# Adjustment
# ---------------------------------------------------------------------------

class AdjustmentRecord(BaseModel):
    user_id: str
    adjustment_date: str              # date this adjustment applies to
    reason: str
    changes: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str    # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    user_id: str
    message: str


class ChatResponse(BaseModel):
    user_id: str
    reply: str
    intent: Optional[str] = None      # detected intent (for debugging)
    structured_data: Optional[Dict[str, Any]] = None   # plan/log rendered by UI


# ---------------------------------------------------------------------------
# API payloads
# ---------------------------------------------------------------------------

class LogRequest(BaseModel):
    user_id: str
    date: str
    workout_done: bool
    food_items: List[str] = []
    calories: int = 0
    notes: str = ""


class CalendarDay(BaseModel):
    date: str
    day_label: str
    status: str                        # pending / completed / missed / adjusted
    workout_type: str
    total_calories: int


class CalendarResponse(BaseModel):
    user_id: str
    week_start: str
    days: List[CalendarDay]


class DayDetailResponse(BaseModel):
    date: str
    day_plan: Optional[DayPlan] = None
    log: Optional[DailyLogResponse] = None
    adjustments: List[AdjustmentRecord] = []


class ProgressResponse(BaseModel):
    user_id: str
    consistency_score: float          # 0-100
    weight_change: Optional[float] = None
    completed_days: int
    total_days: int
    motivational_message: str
    recent_logs: List[Dict[str, Any]] = []

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthResponse(BaseModel):
    user_id: str
    email: str
    name: Optional[str] = None
