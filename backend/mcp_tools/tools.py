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


# ---------------------------------------------------------------------------
# ADK Tool Functions
# ---------------------------------------------------------------------------
# These standalone async functions are auto-wrapped by ADK's LlmAgent
# as FunctionTool objects.  ADK reads the name, docstring, and type hints
# to build the JSON schema the LLM sees.
#
# Each function delegates to execute_tool() to avoid duplicating logic.
# ---------------------------------------------------------------------------

async def tool_save_user_profile(
    user_id: str,
    name: str = "",
    goal: str = "",
    weight: float = 0,
    height: float = 0,
    workout_start: str = "",
    workout_end: str = "",
    location: str = "",
    diet_type: str = "",
    food_access: str = "",
) -> dict:
    """Save or update fields in the user's fitness profile.

    Only pass fields that need to be set or updated.
    goal must be one of: weight_loss, muscle_gain, maintenance.
    diet_type must be one of: veg, non_veg, vegan.
    food_access must be one of: home, hostel, outside.
    workout_start and workout_end in HH:MM format (e.g. 07:00).
    weight in kg, height in cm.

    Returns the updated profile and list of missing fields.
    """
    args: Dict[str, Any] = {"user_id": user_id}
    if name:          args["name"] = name
    if goal:          args["goal"] = goal
    if weight:        args["weight"] = weight
    if height:        args["height"] = height
    if workout_start: args["workout_start"] = workout_start
    if workout_end:   args["workout_end"] = workout_end
    if location:      args["location"] = location
    if diet_type:     args["diet_type"] = diet_type
    if food_access:   args["food_access"] = food_access
    return await execute_tool("save_user_profile", args)


async def tool_get_user_profile(user_id: str) -> dict:
    """Retrieve the current user profile and list of missing fields.

    Returns the profile data, missing_fields list, and onboarding_complete status.
    """
    return await execute_tool("get_user_profile", {"user_id": user_id})


async def tool_get_weekly_plan(user_id: str, week_start: str = "") -> dict:
    """Retrieve the current or most recent weekly fitness plan for the user.

    Optionally filter by week_start (ISO date of Monday, YYYY-MM-DD).
    Returns the full plan with days array, or error if no plan exists.
    """
    args: Dict[str, Any] = {"user_id": user_id}
    if week_start:
        args["week_start"] = week_start
    return await execute_tool("get_weekly_plan", args)


async def tool_get_daily_plan(user_id: str, date: str) -> dict:
    """Get the workout and diet plan for a specific date.

    date must be in ISO format YYYY-MM-DD.
    Returns the day's exercises, meals, calories, and status.
    """
    return await execute_tool("get_daily_plan", {"user_id": user_id, "date": date})


async def tool_log_daily_activity(
    user_id: str,
    date: str,
    workout_done: bool,
    food_items: str = "",
    calories_consumed: int = 0,
    notes: str = "",
) -> dict:
    """Record the user's workout completion and food intake for a given day.

    Call this when the user tells you what they ate or whether they worked out.
    date in ISO format YYYY-MM-DD.
    food_items is a comma-separated string of food items eaten.
    """
    food_list = [f.strip() for f in food_items.split(",") if f.strip()] if food_items else []
    return await execute_tool("log_daily_activity", {
        "user_id": user_id,
        "date": date,
        "workout_done": workout_done,
        "food_items": food_list,
        "calories_consumed": calories_consumed,
        "notes": notes,
    })


async def tool_apply_adjustment(
    user_id: str,
    target_date: str,
    reason: str,
    intensity_delta: str = "maintain",
    calorie_delta: int = 0,
    extra_notes: str = "",
) -> dict:
    """Store an AI-generated adjustment for the next day's plan.

    Use after analysing a daily log to modify tomorrow's workout intensity or diet.
    target_date: the date the adjustment applies to (YYYY-MM-DD).
    intensity_delta: one of increase, decrease, maintain.
    calorie_delta: calories to add (positive) or subtract (negative) from target.
    """
    return await execute_tool("apply_adjustment", {
        "user_id": user_id,
        "target_date": target_date,
        "reason": reason,
        "intensity_delta": intensity_delta,
        "calorie_delta": calorie_delta,
        "extra_notes": extra_notes,
    })


async def tool_get_progress_summary(user_id: str) -> dict:
    """Return consistency score, weight change, and completed days for the user.

    Used to assess the user's overall progress and adherence.
    """
    return await execute_tool("get_progress_summary", {"user_id": user_id})


async def tool_update_day_status(
    user_id: str,
    date: str,
    status: str,
    adjustment_note: str = "",
) -> dict:
    """Update the status of a specific day in the weekly plan.

    status must be one of: pending, completed, missed, adjusted.
    date in ISO format YYYY-MM-DD.
    """
    args: Dict[str, Any] = {
        "user_id": user_id,
        "date": date,
        "status": status,
    }
    if adjustment_note:
        args["adjustment_note"] = adjustment_note
    return await execute_tool("update_day_status", args)


async def tool_modify_plan_days(
    user_id: str,
    reason: str,
    changes_json: str,
) -> dict:
    """Update one or more days in the weekly plan with new exercises, meals, or both.

    Use when the user wants to change workouts or diet preferences.

    changes_json must be a JSON string representing a list of day changes.
    Each change object must have a "date" field (YYYY-MM-DD) and optionally:
      - "exercises": list of exercise objects with name, sets, reps, duration_min, notes
      - "meals": list of meal objects with meal_type (breakfast/lunch/snack/dinner), items, calories, protein_g
      - "workout_type": string like Push, Yoga, Cardio, Rest
      - "total_calories": integer
      - "adjustment_note": string

    Example changes_json:
    [{"date":"2025-01-06","workout_type":"Yoga","exercises":[{"name":"Sun Salutation","sets":3,"reps":"5"}]}]
    """
    import json as _json
    try:
        changes = _json.loads(changes_json)
    except (ValueError, TypeError):
        return {"error": "Invalid JSON in changes_json"}
    return await execute_tool("modify_plan_days", {
        "user_id": user_id,
        "reason": reason,
        "changes": changes,
    })

