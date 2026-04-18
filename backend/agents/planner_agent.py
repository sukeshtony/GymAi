"""
Planner Agent (ADK)
===================
Generates a structured 7-day workout + diet plan using ADK LlmAgent.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai.types import Content, Part

from agents.base import BaseAgent, MODEL
from database import db
from mcp_tools.tools import tool_get_user_profile, tool_get_weekly_plan


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
        {"name": "Push-ups", "sets": 3, "reps": "12-15", "duration_min": 0, "notes": ""},
        {"name": "Pike Push-ups", "sets": 3, "reps": "10", "duration_min": 0, "notes": ""},
        {"name": "Tricep Dips", "sets": 3, "reps": "12", "duration_min": 0, "notes": ""}
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
    tool_functions = [tool_get_user_profile, tool_get_weekly_plan]

    async def generate_plan(
        self,
        user_id: str,
        week_start: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Full plan generation flow:
        1. Validate user profile completeness
        2. Apply smart defaults for optional fields
        3. Ask LLM to generate the plan JSON (with retry)
        4. Parse + save to DB
        5. Return the plan
        """
        if not week_start:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            week_start = monday.isoformat()

        profile = await db.get_user(user_id)
        if not profile:
            return {"error": "User profile not found. Please complete onboarding first."}

        # ── Validate critical fields ──
        critical_fields = ["goal", "weight", "diet_type"]
        missing_critical = [
            f for f in critical_fields
            if not profile.get(f) or profile.get(f) in (0, "", None)
        ]
        if missing_critical:
            return {
                "error": (
                    f"Cannot generate plan — missing critical data: {', '.join(missing_critical)}. "
                    "Please complete your profile first."
                )
            }

        # ── Smart defaults for optional fields (with logging) ──
        defaults_applied = []
        if not profile.get("height"):
            profile["height"] = 170
            defaults_applied.append("height (defaulted to 170 cm)")
        if not profile.get("workout_start"):
            profile["workout_start"] = "07:00"
            defaults_applied.append("workout_start (defaulted to 07:00)")
        if not profile.get("workout_end"):
            profile["workout_end"] = "08:00"
            defaults_applied.append("workout_end (defaulted to 08:00)")
        if not profile.get("location"):
            profile["location"] = "India"
            defaults_applied.append("location (defaulted to India)")
        if not profile.get("food_access"):
            profile["food_access"] = "home"
            defaults_applied.append("food_access (defaulted to home)")

        if defaults_applied:
            logger.warning(
                f"Plan generation for {user_id} used defaults: {', '.join(defaults_applied)}"
            )

        # ── Build prompt ──
        prompt = f"""
Generate a 7-day fitness and diet plan for this user:

User ID: {user_id}
Goal: {profile.get('goal')}
Weight: {profile.get('weight')} kg
Height: {profile.get('height')} cm
Workout window: {profile.get('workout_start')} to {profile.get('workout_end')}
Location: {profile.get('location')}
Diet type: {profile.get('diet_type')}
Food access: {profile.get('food_access')}
Week start (Monday): {week_start}

The days array must have exactly 7 entries, starting from {week_start}.
"""

        # ── Generate with retry on JSON parse failure ──
        plan_data = await self._generate_with_retry(user_id, prompt, max_attempts=2)

        if plan_data is None:
            return {
                "error": (
                    "I had trouble generating your plan. "
                    "This usually resolves itself — please try again in a moment."
                )
            }

        # Save to database
        plan_id = await db.save_weekly_plan(user_id, week_start, plan_data)
        plan_data["db_id"] = plan_id

        return plan_data

    async def _generate_with_retry(
        self, user_id: str, prompt: str, max_attempts: int = 2
    ) -> Optional[Dict[str, Any]]:
        """Call the LLM and parse JSON, retrying with a stricter prompt on failure."""
        last_error = None

        for attempt in range(max_attempts):
            instruction = self.system_prompt
            if attempt > 0:
                # Stricter prompt on retry
                instruction += (
                    "\n\nCRITICAL: Your PREVIOUS response was not valid JSON. "
                    "Return ONLY the raw JSON object. No markdown, no code fences, "
                    "no commentary. Start with { and end with }."
                )
                logger.info(f"Plan generation retry #{attempt} for user {user_id}")

            agent = LlmAgent(
                name="PlanGenerator",
                model=MODEL,
                instruction=instruction,
            )

            runner = InMemoryRunner(agent=agent, app_name="PlanGenerator")
            runner.auto_create_session = True
            user_content = Content(parts=[Part.from_text(text=prompt)])

            reply_parts: List[str] = []
            async for event in runner.run_async(
                user_id=user_id,
                session_id=f"plan_{user_id}_{attempt}",
                new_message=user_content,
            ):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            reply_parts.append(part.text)

            raw_text = "".join(reply_parts).strip()

            # Extract JSON from response (handle markdown code blocks)
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()

            try:
                return json.loads(raw_text)
            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(
                    f"Plan JSON parse failed (attempt {attempt + 1}/{max_attempts}) "
                    f"for {user_id}: {e}"
                )

        logger.error(f"Plan generation failed after {max_attempts} attempts for {user_id}")
        return None

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
