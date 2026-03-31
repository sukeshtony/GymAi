"""
MCP Tool Definitions + Executor
================================
Each tool is defined in two parts:
  1. TOOL_DEFINITIONS  – the JSON schema Claude sees (tool_use API format)
  2. execute_tool()    – the Python function that actually runs it

Agents call Claude with TOOL_DEFINITIONS attached, then pass tool_use
blocks to execute_tool() to get real results back.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from database import db


# ---------------------------------------------------------------------------
# Tool Schemas (Claude sees these)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "save_user_profile",
        "description": (
            "Save or update fields in the user's profile. "
            "Only pass fields that need to be set or updated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":       {"type": "string"},
                "name":          {"type": "string"},
                "goal":          {"type": "string", "enum": ["weight_loss", "muscle_gain", "maintenance"]},
                "weight":        {"type": "number", "description": "Weight in kg"},
                "height":        {"type": "number", "description": "Height in cm"},
                "workout_start": {"type": "string", "description": "HH:MM format, e.g. 07:00"},
                "workout_end":   {"type": "string", "description": "HH:MM format, e.g. 08:00"},
                "location":      {"type": "string", "description": "City name only"},
                "diet_type":     {"type": "string", "enum": ["veg", "non_veg", "vegan"]},
                "food_access":   {"type": "string", "enum": ["home", "hostel", "outside"]},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "get_user_profile",
        "description": "Retrieve the current user profile and list of missing fields.",
        "input_schema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
        },
    },
    {
        "name": "generate_weekly_plan",
        "description": (
            "Trigger the Planner Agent to create a 7-day workout+diet plan "
            "and store it. Returns the plan as structured JSON."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":     {"type": "string"},
                "week_start":  {"type": "string", "description": "ISO date of Monday (YYYY-MM-DD)"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "get_weekly_plan",
        "description": "Retrieve the current or most recent weekly plan for the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":    {"type": "string"},
                "week_start": {"type": "string", "description": "Optional ISO date filter"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "get_daily_plan",
        "description": "Get the workout and diet plan for a specific date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "date":    {"type": "string", "description": "ISO date YYYY-MM-DD"},
            },
            "required": ["user_id", "date"],
        },
    },
    {
        "name": "log_daily_activity",
        "description": (
            "Record the user's workout completion and food intake for a given day. "
            "Call this when the user tells you what they ate or whether they worked out."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":           {"type": "string"},
                "date":              {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "workout_done":      {"type": "boolean"},
                "food_items":        {"type": "array", "items": {"type": "string"}},
                "calories_consumed": {"type": "integer"},
                "notes":             {"type": "string"},
            },
            "required": ["user_id", "date", "workout_done"],
        },
    },
    {
        "name": "apply_adjustment",
        "description": (
            "Store an AI-generated adjustment for the next day's plan. "
            "Use this after analysing a daily log to modify tomorrow's workout intensity or diet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":         {"type": "string"},
                "target_date":     {"type": "string", "description": "Date the adjustment applies to"},
                "reason":          {"type": "string"},
                "intensity_delta": {
                    "type": "string",
                    "enum": ["increase", "decrease", "maintain"],
                    "description": "Change to workout intensity",
                },
                "calorie_delta":   {
                    "type": "integer",
                    "description": "Calories to add (positive) or subtract (negative) from target",
                },
                "extra_notes":     {"type": "string"},
            },
            "required": ["user_id", "target_date", "reason"],
        },
    },
    {
        "name": "get_progress_summary",
        "description": "Return consistency score, weight change, completed days for the user.",
        "input_schema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
        },
    },
    {
        "name": "update_day_status",
        "description": "Update the status of a specific day in the weekly plan (completed/missed/adjusted).",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "date":    {"type": "string"},
                "status":  {"type": "string", "enum": ["pending", "completed", "missed", "adjusted"]},
                "adjustment_note": {"type": "string"},
            },
            "required": ["user_id", "date", "status"],
        },
    },
    {
        "name": "modify_plan_days",
        "description": (
            "Update one or more days in the weekly plan with new exercises, meals, or both. "
            "Use when the user wants to change workouts or diet preferences. "
            "Only include the fields you want to change in each day entry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "reason":  {"type": "string", "description": "Why the plan is being modified"},
                "changes": {
                    "type": "array",
                    "description": "List of per-day changes to apply",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                            "workout_type": {"type": "string", "description": "e.g. Push, Yoga, Cardio, Rest"},
                            "exercises": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name":         {"type": "string"},
                                        "sets":         {"type": "integer"},
                                        "reps":         {"type": "string"},
                                        "duration_min": {"type": "integer"},
                                        "notes":        {"type": "string"},
                                    },
                                    "required": ["name"],
                                },
                            },
                            "meals": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "meal_type":  {"type": "string", "enum": ["breakfast", "lunch", "snack", "dinner"]},
                                        "items":      {"type": "array", "items": {"type": "string"}},
                                        "calories":   {"type": "integer"},
                                        "protein_g":  {"type": "integer"},
                                        "notes":      {"type": "string"},
                                    },
                                    "required": ["meal_type", "items", "calories"],
                                },
                            },
                            "total_calories":   {"type": "integer"},
                            "adjustment_note":  {"type": "string"},
                        },
                        "required": ["date"],
                    },
                },
            },
            "required": ["user_id", "changes", "reason"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool Executor
# ---------------------------------------------------------------------------

async def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Any:
    """Dispatch a Claude tool_use call to the correct DB operation."""

    if tool_name == "save_user_profile":
        user_id = tool_input.pop("user_id")
        new_weight = tool_input.get("weight")
        updated = await db.upsert_user(user_id, tool_input)
        # Record a weight snapshot every time weight is explicitly provided
        if new_weight is not None:
            await db.record_weight(user_id, float(new_weight))
        missing = await db.recalculate_missing_fields(user_id)
        return {
            "success": True,
            "profile": updated,
            "missing_fields": missing,
            "onboarding_complete": len(missing) == 0,
        }

    elif tool_name == "get_user_profile":
        user_id = tool_input["user_id"]
        profile = await db.get_user(user_id)
        state = await db.get_user_state(user_id)
        return {
            "profile": profile,
            "missing_fields": state["missing_fields"],
            "onboarding_complete": bool(state["onboarding_complete"]),
        }

    elif tool_name == "generate_weekly_plan":
        # Actual generation is done inside the PlannerAgent;
        # here we just ensure a week_start is set
        from datetime import date as d_
        week_start = tool_input.get("week_start") or _this_monday()
        return {"week_start": week_start, "trigger": "generate_plan"}

    elif tool_name == "get_weekly_plan":
        user_id = tool_input["user_id"]
        week_start = tool_input.get("week_start")
        plan = await db.get_weekly_plan(user_id, week_start)
        return plan or {"error": "No plan found. Ask the user if they want to generate one."}

    elif tool_name == "get_daily_plan":
        user_id = tool_input["user_id"]
        target_date = tool_input["date"]
        plan = await db.get_weekly_plan(user_id)
        if not plan:
            return {"error": "No plan exists for this user yet."}
        for day in plan["plan_data"]["days"]:
            if day["date"] == target_date:
                return day
        return {"error": f"No plan found for {target_date}."}

    elif tool_name == "log_daily_activity":
        row_id = await db.log_daily_activity(
            user_id=tool_input["user_id"],
            log_date=tool_input["date"],
            workout_done=tool_input["workout_done"],
            food_intake=tool_input.get("food_items", []),
            calories_consumed=tool_input.get("calories_consumed", 0),
            notes=tool_input.get("notes", ""),
        )
        # Also update day status in plan
        status = "completed" if tool_input["workout_done"] else "missed"
        plan = await db.get_weekly_plan(tool_input["user_id"])
        if plan:
            days = plan["plan_data"]["days"]
            for i, day in enumerate(days):
                if day["date"] == tool_input["date"]:
                    day["status"] = status
                    await db.update_day_plan(
                        tool_input["user_id"], plan["week_start"], i, day
                    )
                    break
        return {"success": True, "log_id": row_id, "status_updated": status}

    elif tool_name == "apply_adjustment":
        changes = {
            "intensity_delta": tool_input.get("intensity_delta", "maintain"),
            "calorie_delta":   tool_input.get("calorie_delta", 0),
            "extra_notes":     tool_input.get("extra_notes", ""),
        }
        adj_id = await db.save_adjustment(
            user_id=tool_input["user_id"],
            adjustment_date=tool_input["target_date"],
            reason=tool_input["reason"],
            changes=changes,
        )
        # Patch the day plan with adjustment_note
        plan = await db.get_weekly_plan(tool_input["user_id"])
        if plan:
            days = plan["plan_data"]["days"]
            for i, day in enumerate(days):
                if day["date"] == tool_input["target_date"]:
                    day["status"] = "adjusted"
                    day["adjustment_note"] = tool_input.get("extra_notes", tool_input["reason"])
                    if changes["calorie_delta"]:
                        day["total_calories"] = max(
                            1200, day["total_calories"] + changes["calorie_delta"]
                        )
                    await db.update_day_plan(
                        tool_input["user_id"], plan["week_start"], i, day
                    )
                    break
        return {"success": True, "adjustment_id": adj_id}

    elif tool_name == "get_progress_summary":
        user_id = tool_input["user_id"]
        logs = await db.get_recent_logs(user_id, days=30)
        completed = sum(1 for l in logs if l["workout_done"])
        total = len(logs)
        score = round((completed / total * 100) if total else 0, 1)
        profile = await db.get_user(user_id)
        return {
            "consistency_score": score,
            "completed_days": completed,
            "total_logged_days": total,
            "current_weight": profile.get("weight") if profile else None,
        }

    elif tool_name == "update_day_status":
        plan = await db.get_weekly_plan(tool_input["user_id"])
        if not plan:
            return {"error": "No plan found"}
        days = plan["plan_data"]["days"]
        for i, day in enumerate(days):
            if day["date"] == tool_input["date"]:
                day["status"] = tool_input["status"]
                if tool_input.get("adjustment_note"):
                    day["adjustment_note"] = tool_input["adjustment_note"]
                await db.update_day_plan(
                    tool_input["user_id"], plan["week_start"], i, day
                )
                return {"success": True}
        return {"error": "Date not found in plan"}

    elif tool_name == "modify_plan_days":
        user_id = tool_input["user_id"]
        reason  = tool_input.get("reason", "User requested plan modification")
        changes = tool_input.get("changes", [])

        plan = await db.get_weekly_plan(user_id)
        if not plan:
            return {"error": "No plan found to modify."}

        days = plan["plan_data"]["days"]
        modified_dates: List[str] = []

        for change in changes:
            target_date = change.get("date")
            for i, day in enumerate(days):
                if day["date"] == target_date:
                    if "exercises" in change:
                        day["exercises"] = change["exercises"]
                    if "meals" in change:
                        day["meals"] = change["meals"]
                    if "workout_type" in change:
                        day["workout_type"] = change["workout_type"]
                    if "total_calories" in change:
                        day["total_calories"] = change["total_calories"]
                    day["status"] = "adjusted"
                    day["adjustment_note"] = change.get("adjustment_note", reason)
                    await db.update_day_plan(user_id, plan["week_start"], i, day)
                    modified_dates.append(target_date)
                    break

        if modified_dates:
            await db.save_adjustment(
                user_id=user_id,
                adjustment_date=modified_dates[0],
                reason=reason,
                changes={"modified_dates": modified_dates, "type": "user_preference"},
            )

        return {"success": True, "modified_dates": modified_dates, "reason": reason}

    return {"error": f"Unknown tool: {tool_name}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _this_monday() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()
