"""
Planner Agent
=============
Generates a structured 7-day workout + diet plan that fits inside
the user's fixed time window. Returns structured JSON for the UI.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import google.generativeai as genai

from agents.base import BaseAgent, MODEL
from database import db
from mcp_tools.tools import TOOL_DEFINITIONS, execute_tool


_PLANNER_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] in (
    "get_user_profile", "get_weekly_plan"
)]

SYSTEM_PROMPT = """You are an expert fitness and nutrition planner.

Given a user's profile, generate a COMPLETE 7-day fitness + diet plan as structured JSON.

IMPORTANT RULES:
1. ALL workouts must fit exactly within the user's workout_start → workout_end window.
2. Include at least one rest day per week.
3. Alternate muscle groups (Push / Pull / Legs / Core / Cardio / Full Body / Rest).
4. Diet must match the user's diet_type (veg/non_veg/vegan) and food_access.
5. Calorie targets must align with the goal (deficit for weight_loss, surplus for muscle_gain).
6. Each meal must list specific food items available in the user's city/access level.

OUTPUT FORMAT – return ONLY this JSON (no extra text):
{
  "user_id": "<user_id>",
  "week_start": "<YYYY-MM-DD>",
  "goal_summary": "<one sentence>",
  "weekly_calories": <number>,
  "days": [
    {
      "day_index": 0,
      "date": "<YYYY-MM-DD>",
      "day_label": "Monday",
      "workout_type": "Push",
      "workout_start": "<HH:MM>",
      "workout_end": "<HH:MM>",
      "exercises": [
        {"name": "Push-ups", "sets": 3, "reps": "12-15", "duration_min": null, "notes": ""},
        {"name": "Pike Push-ups", "sets": 3, "reps": "10", "duration_min": null, "notes": ""},
        {"name": "Tricep Dips", "sets": 3, "reps": "12", "duration_min": null, "notes": ""}
      ],
      "meals": [
        {"meal_type": "breakfast", "items": ["Oats with banana", "Green tea"], "calories": 350, "protein_g": 12, "notes": ""},
        {"meal_type": "lunch",     "items": ["Dal rice", "Salad"], "calories": 550, "protein_g": 22, "notes": ""},
        {"meal_type": "snack",     "items": ["Peanut butter toast"], "calories": 200, "protein_g": 8, "notes": ""},
        {"meal_type": "dinner",    "items": ["Paneer sabzi", "Chapati"], "calories": 500, "protein_g": 25, "notes": ""}
      ],
      "total_calories": 1600,
      "water_ml": 2500,
      "status": "pending",
      "adjustment_note": null
    }
    // ... 6 more days
  ]
}
"""


class PlannerAgent(BaseAgent):
    name = "PlannerAgent"
    system_prompt = SYSTEM_PROMPT
    tools = _PLANNER_TOOLS
    max_iterations = 3  # Plan generation needs fewer loops

    async def generate_plan(
        self,
        user_id: str,
        week_start: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Full plan generation flow:
        1. Load user profile from DB
        2. Ask Claude to generate the plan JSON
        3. Parse + save to DB
        4. Return the plan
        """
        if not week_start:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            week_start = monday.isoformat()

        profile = await db.get_user(user_id)
        if not profile:
            return {"error": "User profile not found. Please complete onboarding first."}

        # Build a prompt with all profile details
        prompt = f"""
Generate a 7-day fitness and diet plan for this user:

User ID: {user_id}
Goal: {profile.get('goal', 'not set')}
Weight: {profile.get('weight', 'unknown')} kg
Height: {profile.get('height', 'unknown')} cm
Workout window: {profile.get('workout_start', '07:00')} to {profile.get('workout_end', '08:00')}
Location: {profile.get('location', 'India')}
Diet type: {profile.get('diet_type', 'veg')}
Food access: {profile.get('food_access', 'home')}
Week start (Monday): {week_start}

The days array must have exactly 7 entries, starting from {week_start}.
"""

        model = genai.GenerativeModel(
            model_name=MODEL,
            system_instruction=self.system_prompt,
        )
        response = model.generate_content(prompt)
        raw_text = response.text.strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()

        try:
            plan_data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            return {"error": f"Failed to parse plan JSON: {e}", "raw": raw_text}

        # Save to database
        plan_id = await db.save_weekly_plan(user_id, week_start, plan_data)
        plan_data["db_id"] = plan_id

        return plan_data

    async def run(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        user_id = (extra_context or {}).get("user_id", "default_user")
        week_start = (extra_context or {}).get("week_start")
        plan = await self.generate_plan(user_id, week_start)
        if "error" in plan:
            return {"reply": f"Sorry, I couldn't generate a plan: {plan['error']}", "structured_data": {}}
        return {
            "reply": (
                "Your 7-day fitness and diet plan is ready! "
                "Check the calendar view to see each day's workout and meals."
            ),
            "structured_data": {"plan": plan},
            "tool_results": [],
        }
