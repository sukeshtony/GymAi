"""
Modification Agent
==================
Handles user requests to change their existing workout or diet plan.

Examples:
  - "I don't like running, replace it with cycling"
  - "I want more protein in my meals"
  - "Change my Tuesday workout to yoga"
  - "I don't have a gym, give me home workouts"
  - "Replace rice with roti in my meals"
  - "I hate push-ups, suggest alternatives"
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from mcp_tools.tools import TOOL_DEFINITIONS

_MOD_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] in (
    "get_weekly_plan", "get_user_profile", "modify_plan_days",
)]

SYSTEM_PROMPT = """You are a personalized fitness plan editor.

Your job: understand what the user wants to change in their workout or diet plan,
then update the plan to match their preferences.

WORKFLOW:
1. Call get_user_profile to know the user's constraints (diet_type, food_access, goal, workout window).
2. Call get_weekly_plan to see the current plan.
3. Figure out which days and which parts (exercises / meals / both) need to change.
4. Generate the replacement exercises or meals — keep them realistic and appropriate.
5. Call modify_plan_days with all the changes bundled together.
6. Tell the user what you changed, and why it still fits their goal.

RULES FOR MODIFYING WORKOUTS:
- Keep total workout duration within the user's workout_start → workout_end window.
- Maintain the same muscle-group focus for the day (e.g. if it was a Push day, keep it Push).
- If the user asks for home workouts, replace gym equipment exercises with bodyweight alternatives.
- If the user specifies a preferred exercise (e.g. yoga, cycling, swimming), use it.
- Adjust sets/reps so difficulty stays appropriate for the user's goal.

RULES FOR MODIFYING MEALS:
- Respect diet_type strictly: veg users get no meat/eggs, vegan users get no dairy.
- Respect food_access: hostel/outside users get simpler, accessible food options.
- Keep total_calories roughly the same as the original day unless the user explicitly asks to change it.
- Keep protein_g at least 0.8g per kg of body weight per day.
- If the user dislikes a specific food, remove it from ALL days it appears.
- If the user wants a specific food added, include it sensibly in the relevant meals.

HANDLING SCOPE:
- "Change today's workout" → modify only today's date.
- "I don't like X" → remove X from all days it appears.
- "Change my diet plan" → modify meals for all 7 days.
- "Replace exercises this week" → modify exercises for all remaining pending days.
- Be smart about scope — don't modify completed/missed days unless the user insists.

Always pass structured day objects to modify_plan_days — include ONLY the fields you are changing
(exercises, meals, workout_type, total_calories, adjustment_note). Always include the date field.
"""


class ModificationAgent(BaseAgent):
    name = "ModificationAgent"
    system_prompt = SYSTEM_PROMPT
    tools = _MOD_TOOLS
    max_iterations = 6

    async def run(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        user_id = (extra_context or {}).get("user_id", "default_user")
        enriched = (
            f"[user_id: {user_id}]\n"
            f"The user wants to change their plan: {user_message}\n\n"
            "Please fetch the profile and current plan, understand what to modify, "
            "then apply the changes using modify_plan_days."
        )
        result = await super().run(enriched, conversation_history, extra_context)
        result["structured_data"]["plan_modified"] = True
        return result
