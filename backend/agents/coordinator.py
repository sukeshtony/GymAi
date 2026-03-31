"""
Primary Coordinator Agent
=========================
Entry point for all /chat requests.

Workflow:
  1. Detect intent from user message using Claude
  2. Route to the correct sub-agent
  3. If profile is incomplete → always go to ProfileAgent first
  4. After logging → trigger AdjustmentAgent automatically
  5. Return unified response with reply + structured_data
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import google.generativeai as genai

from agents.profile_agent import ProfileAgent
from agents.planner_agent import PlannerAgent
from agents.adjustment_agent import AdjustmentAgent
from agents.nutrition_agent import NutritionAgent
from agents.coach_agent import CoachAgent
from agents.modification_agent import ModificationAgent
from database import db

MODEL = os.getenv("MODEL_ID", "gemini-2.5-pro")
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Intent detection prompt – lightweight, fast
INTENT_SYSTEM = """You are an intent classifier for a fitness app chatbot.
Classify the user message into EXACTLY ONE of these intents:

- "profile"      – user is providing profile data (weight, goal, diet, time, location) or updating it
- "log_activity" – user is logging a workout (done/skipped) or food intake
- "get_plan"     – user wants to see their plan, generate a plan, or ask about exercises
- "modify_plan"  – user wants to CHANGE their existing plan: disliked exercises, preferred foods,
                   replacing meals, requesting different workouts, suggesting alternatives,
                   or saying they don't like something in their current plan
- "nutrition"    – user is asking about food, meals, diet, or calories (general advice, not plan edits)
- "motivation"   – user wants encouragement, is feeling down, or asking about progress
- "general"      – greetings, anything else

Return ONLY a JSON object: {"intent": "<intent>", "confidence": 0.9}
"""


class CoordinatorAgent:

    def __init__(self) -> None:
        self.profile_agent = ProfileAgent()
        self.planner_agent = PlannerAgent()
        self.adjustment_agent = AdjustmentAgent()
        self.nutrition_agent = NutritionAgent()
        self.coach_agent = CoachAgent()
        self.modification_agent = ModificationAgent()

    async def handle(
        self,
        user_id: str,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Main entry point. Returns {reply, intent, structured_data}."""

        history = conversation_history or []

        # ----------------------------------------------------------------
        # 1. Check onboarding status
        # ----------------------------------------------------------------
        state = await db.get_user_state(user_id)
        missing = state.get("missing_fields", [])
        onboarded = state.get("onboarding_complete", 0)

        # ----------------------------------------------------------------
        # 2. Detect intent
        # ----------------------------------------------------------------
        intent = await self._detect_intent(message, history)

        # ----------------------------------------------------------------
        # 3. Force profile collection if not onboarded
        #    (unless user is explicitly logging or asking about plan)
        # ----------------------------------------------------------------
        ctx: Dict[str, Any] = {"user_id": user_id}

        if not onboarded and intent not in ("log_activity", "motivation"):
            result = await self.profile_agent.run(message, history, ctx)
            # After profile update, check if we should auto-generate plan
            updated_state = await db.get_user_state(user_id)
            if updated_state.get("onboarding_complete") and not await db.get_weekly_plan(user_id):
                plan_result = await self.planner_agent.run("generate", [], ctx)
                result["reply"] += (
                    "\n\n🗓️ Your personalized 7-day plan has been generated! "
                    "Check the calendar tab to see your full week."
                )
                result["structured_data"] = {**result.get("structured_data", {}),
                                             **(plan_result.get("structured_data", {}))}
            return {
                "reply": result["reply"],
                "intent": "profile",
                "structured_data": result.get("structured_data", {}),
            }

        # ----------------------------------------------------------------
        # 4. Route to correct agent
        # ----------------------------------------------------------------
        if intent == "profile":
            result = await self.profile_agent.run(message, history, ctx)
            # Auto-generate plan if just completed onboarding
            updated_state = await db.get_user_state(user_id)
            if updated_state.get("onboarding_complete") and not await db.get_weekly_plan(user_id):
                plan_result = await self.planner_agent.run("generate", [], ctx)
                result["reply"] += (
                    "\n\n🗓️ Your 7-day plan is ready! "
                    "Check the calendar to see your workouts and meals."
                )
                result["structured_data"] = {**result.get("structured_data", {}),
                                             **(plan_result.get("structured_data", {}))}

        elif intent == "log_activity":
            # Log via adjustment agent (which also calls log_daily_activity tool)
            from datetime import date
            ctx["log_date"] = date.today().isoformat()
            result = await self.adjustment_agent.run(message, history, ctx)

        elif intent == "get_plan":
            existing_plan = await db.get_weekly_plan(user_id)
            if not existing_plan:
                result = await self.planner_agent.run("generate", [], ctx)
            else:
                # User wants to see/discuss the plan
                result = await self.planner_agent.run(message, history, ctx)
                result["structured_data"]["plan"] = existing_plan["plan_data"]

        elif intent == "modify_plan":
            existing_plan = await db.get_weekly_plan(user_id)
            if not existing_plan:
                # No plan to modify — generate one first
                result = await self.planner_agent.run("generate", [], ctx)
                result["reply"] = (
                    "You don't have a plan yet, so I've generated one for you! "
                    "You can now ask me to change any part of it."
                )
            else:
                result = await self.modification_agent.run(message, history, ctx)
                result["structured_data"]["refresh_calendar"] = True

        elif intent == "nutrition":
            result = await self.nutrition_agent.run(message, history, ctx)

        elif intent == "motivation":
            result = await self.coach_agent.run(message, history, ctx)

        else:  # general
            result = await self._general_reply(message, history, user_id)

        return {
            "reply": result.get("reply", ""),
            "intent": intent,
            "structured_data": result.get("structured_data", {}),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _detect_intent(
        self, message: str, history: List[Dict[str, str]]
    ) -> str:
        model = genai.GenerativeModel(
            model_name=MODEL,
            system_instruction=INTENT_SYSTEM,
        )
        # Pass the last few messages as context plus the new message
        recent = history[-4:] if len(history) > 4 else history
        ctx = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
        prompt = f"{ctx}\nuser: {message}" if ctx else message
        response = model.generate_content(prompt)
        try:
            raw = response.text.strip()
            # Strip markdown code fences if present
            if "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            data = json.loads(raw)
            return data.get("intent", "general")
        except Exception:
            return "general"

    async def _general_reply(
        self, message: str, history: List[Dict], user_id: str
    ) -> Dict[str, Any]:
        profile = await db.get_user(user_id)
        name = (profile or {}).get("name", "there")
        model = genai.GenerativeModel(
            model_name=MODEL,
            system_instruction=(
                f"You are FitBot, a helpful fitness assistant. "
                f"The user's name is {name}. "
                "Be concise, friendly, and always steer conversation toward fitness goals."
            ),
        )
        # Build history for context
        gemini_history = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]}
            for m in history[-6:]
        ]
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(message)
        return {
            "reply": response.text,
            "structured_data": {},
            "tool_results": [],
        }
