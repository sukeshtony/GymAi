"""
Nutrition Agent (ADK)
=====================
Suggests realistic meals based on user location, diet type, and food access.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from mcp_tools.tools import tool_get_user_profile, tool_get_daily_plan


SYSTEM_PROMPT = """You are an expert nutritionist specializing in Indian and regional diets.

When asked for meal suggestions:
1. First call tool_get_user_profile to understand the user's diet type, food access, and location.
2. Suggest meals that are:
   - Realistic for the user's food_access level (home-cooked vs hostel vs outside food)
   - Available in their city/region
   - Aligned with their diet type (veg/non_veg/vegan)
   - Calorie and macro appropriate for their goal
3. Always return structured JSON like:
   {
     "meals": [
       {"meal_type": "breakfast", "items": ["..."], "calories": 350, "protein_g": 15, "notes": "..."},
       ...
     ],
     "total_calories": 1600,
     "total_protein_g": 80,
     "hydration_tip": "Drink 3L water today",
     "tip": "Include a banana before your workout for quick energy"
   }
4. If the user asks about a specific food ("Can I eat biryani?"), give a direct answer with quantity guidance.
5. Never be preachy. Be practical and supportive.
"""


class NutritionAgent(BaseAgent):
    name = "NutritionAgent"
    system_prompt = SYSTEM_PROMPT
    tool_functions = [tool_get_user_profile, tool_get_daily_plan]

    async def run(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        user_id = (extra_context or {}).get("user_id", "default_user")
        enriched = f"[user_id: {user_id}]\n{user_message}"
        return await super().run(enriched, conversation_history, extra_context)
