"""
Adjustment Agent
================
CRITICAL AGENT – analyses daily logs and adjusts the NEXT day's plan.
Rules:
  - Workout skipped → increase intensity next day (add 1 set per exercise)
  - Overeating (>200 cal over target) → reduce next day's calories
  - Good performance (workout done + within calories) → maintain or reward
  - Does NOT change the workout time window – only intensity and diet targets
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from mcp_tools.tools import TOOL_DEFINITIONS

_ADJ_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] in (
    "get_daily_plan", "log_daily_activity", "apply_adjustment",
    "get_weekly_plan", "get_progress_summary",
)]

SYSTEM_PROMPT = """You are a smart fitness adjustment coach.

Your job: after a user logs their daily activity, analyse their log and decide
how to adjust the NEXT day's plan to keep them on track toward their goal.

RULES (strictly follow these):
1. Never change the workout time window.
2. Only change: exercise intensity (sets/reps) and calorie target.
3. If workout was skipped:
   → intensity_delta = "increase"
   → reason = "Workout skipped yesterday – making tomorrow slightly more challenging to compensate"
4. If calories_consumed > today's target + 200:
   → calorie_delta = -(overage * 0.5)   (reduce by half the overage, rounded to 50)
   → reason = "Calorie surplus detected – adjusting tomorrow's target"
5. If workout done AND within 200 cal of target:
   → intensity_delta = "maintain"
   → calorie_delta = 0
   → reason = "Great consistency! Keeping tomorrow's plan the same"
6. If workout done AND 3+ consecutive good days:
   → intensity_delta = "increase"
   → reason = "Excellent streak! Increasing intensity as a reward"

Always call apply_adjustment at the end with the computed values.
Then give a short, motivating message to the user explaining what changed.
"""


class AdjustmentAgent(BaseAgent):
    name = "AdjustmentAgent"
    system_prompt = SYSTEM_PROMPT
    tools = _ADJ_TOOLS

    async def run(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        user_id = (extra_context or {}).get("user_id", "default_user")
        log_date = (extra_context or {}).get("log_date", "")
        enriched = (
            f"[user_id: {user_id}] [logged_date: {log_date}]\n"
            f"Daily log submitted: {user_message}\n"
            "Please analyse this log and apply the appropriate adjustment for tomorrow."
        )
        return await super().run(enriched, conversation_history, extra_context)
