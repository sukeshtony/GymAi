"""
Base agent — ADK-powered agent with LlmAgent + InMemoryRunner.
===============================================================
Replaces the manual Gemini API loop with Google ADK abstractions.
Each subclass still defines: name, system_prompt, tool_functions.
The run() method returns the same dict shape as before so all
callers (coordinator, main.py) continue to work unchanged.
"""
from __future__ import annotations

import os
import uuid
import json
from typing import Any, Callable, Dict, List, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai.types import Content, Part

MODEL = os.getenv("MODEL_ID", "gemini-2.5-flash")


class BaseAgent:
    """
    ADK-powered agent wrapper.

    Subclasses set:
      - name: str
      - system_prompt: str
      - tool_functions: list of async callables (ADK auto-wraps them)

    The run() method:
      1. Builds an LlmAgent with the prompt + tools
      2. Uses InMemoryRunner to execute the agent
      3. Collects all response text
      4. Returns { "reply": str, "tool_results": list, "structured_data": dict }
    """

    name: str = "BaseAgent"
    system_prompt: str = "You are a helpful AI assistant."
    tool_functions: List[Callable] = []

    async def run(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute the agent with ADK and return the same dict shape as before.
        """
        # Build instruction with conversation history for context
        instruction = self.system_prompt
        if conversation_history:
            history_text = "\n".join(
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in (conversation_history[-6:])  # last 6 messages
            )
            instruction += f"\n\nRecent conversation history:\n{history_text}"

        # Create ADK LlmAgent
        agent = LlmAgent(
            name=self.name,
            model=MODEL,
            instruction=instruction,
            tools=self.tool_functions,
        )

        # Create runner and execute
        runner = InMemoryRunner(agent=agent, app_name=self.name)
        runner.auto_create_session = True
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        user_id = (extra_context or {}).get("user_id", "default_user")

        user_content = Content(parts=[Part.from_text(text=user_message)])

        # Collect all response text
        reply_parts: List[str] = []
        tool_results: List[Dict] = []
        structured_data: Dict[str, Any] = {}

        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_content,
        ):
            # Extract text from agent responses
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        reply_parts.append(part.text)
                    if hasattr(part, "function_call") and part.function_call:
                        tool_results.append({
                            "tool": part.function_call.name,
                            "args": dict(part.function_call.args) if part.function_call.args else {},
                        })
                    if hasattr(part, "function_response") and part.function_response:
                        resp = part.function_response.response
                        if isinstance(resp, dict):
                            structured_data.update(resp)

        reply = "".join(reply_parts).strip()

        return {
            "reply": reply or "I've processed your request.",
            "tool_results": tool_results,
            "structured_data": structured_data,
        }
