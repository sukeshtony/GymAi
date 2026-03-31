"""
Profile Agent
=============
Collects user data via friendly conversation, stores via MCP tools.
Tracks missing fields and asks one question at a time.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from mcp_tools.tools import TOOL_DEFINITIONS


_PROFILE_TOOLS = [t for t in TOOL_DEFINITIONS if t["name"] in (
    "save_user_profile", "get_user_profile"
)]

SYSTEM_PROMPT = """You are a friendly fitness onboarding assistant named Alex.

Your job is to collect the following user profile data one question at a time:
  1. goal       – "weight_loss", "muscle_gain", or "maintenance"
  2. weight     – in kg (ask "what is your current weight in kg?")
  3. height     – in cm (optional, ask after weight)
  4. workout_start + workout_end – "What time window do you want to work out? (e.g. 7 AM to 8 AM)"
  5. location   – city name only
  6. diet_type  – "veg", "non_veg", or "vegan"
  7. food_access – "home", "hostel", or "outside"

Rules:
- ALWAYS call get_user_profile first to see what is already known.
- Ask only ONE question per turn.
- When the user provides a value, immediately call save_user_profile to store it.
- After saving, check missing_fields returned by the tool.
- If all fields are filled → say "Great! Your profile is complete. I'll generate your fitness plan now!"
- Be warm, encouraging, and conversational.
- If the user updates an existing field (e.g. "my weight is now 72"), save it immediately.
- Never ask for data that is already stored.
- Format workout times as "HH:MM" (24h), e.g. "07:00".
"""


class ProfileAgent(BaseAgent):
    name = "ProfileAgent"
    system_prompt = SYSTEM_PROMPT
    tools = _PROFILE_TOOLS

    async def run(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # Inject current user_id into the message so Claude can pass it to tools
        user_id = (extra_context or {}).get("user_id", "default_user")
        enriched = f"[user_id: {user_id}]\n{user_message}"
        return await super().run(enriched, conversation_history, extra_context)
