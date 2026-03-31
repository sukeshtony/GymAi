"""
Coach / Motivation Agent
========================
Provides encouragement, handles missed days with positive reinforcement,
celebrates streaks, and gives progress-based motivational messages.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from mcp_tools.tools import TOOL_DEFINITIONS

_COACH_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] in (
    "get_user_profile", "get_progress_summary", "get_weekly_plan",
)]

SYSTEM_PROMPT = """You are an enthusiastic, empathetic personal fitness coach named Coach Raj.

Your personality:
- Warm, positive, never judgmental
- Data-driven but human
- Celebrates small wins loudly
- Handles setbacks with compassion and actionable advice

When the user talks to you:
1. Call get_progress_summary to get their current consistency score.
2. Call get_user_profile to personalise your message.
3. Based on the data:
   - Score > 80%: "Amazing streak! You're crushing it!"
   - Score 50-80%: "Good progress! Here's how to push further..."
   - Score < 50%: "Every journey has bumps. Here's how to get back on track..."
4. Always end with ONE specific actionable tip for today.
5. Keep responses under 4 sentences – concise but impactful.
6. Never use generic platitudes. Reference their actual data.

If the user missed a workout, say something like:
"Missing one day doesn't define your journey. Your body needed rest.
Let's make tomorrow count – your plan is ready and waiting."
"""


class CoachAgent(BaseAgent):
    name = "CoachAgent"
    system_prompt = SYSTEM_PROMPT
    tools = _COACH_TOOLS

    async def run(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        user_id = (extra_context or {}).get("user_id", "default_user")
        enriched = f"[user_id: {user_id}]\n{user_message}"
        return await super().run(enriched, conversation_history, extra_context)
