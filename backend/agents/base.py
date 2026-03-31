"""
Base agent — shared Gemini API call loop with function-calling handling.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import google.generativeai as genai
import google.generativeai.protos as protos

from mcp_tools.tools import execute_tool

MODEL = os.getenv("MODEL_ID", "gemini-2.5-pro")
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))


def _to_gemini_tools(anthropic_tools: List[Dict]) -> Optional[List[Dict]]:
    """
    Convert Anthropic tool format → Gemini function_declarations dict format.

    Anthropic: { name, description, input_schema: { type, properties, required } }
    Gemini:    [{ "function_declarations": [{ name, description, parameters: {...} }] }]

    The parameters schema is identical JSON Schema — only the key name changes.
    """
    if not anthropic_tools:
        return None
    return [{
        "function_declarations": [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],   # same JSON Schema, different key
            }
            for t in anthropic_tools
        ]
    }]


def _deep_convert(obj: Any) -> Any:
    """Recursively convert protobuf MapComposite / RepeatedComposite to plain dicts/lists."""
    if hasattr(obj, "items"):          # MapComposite or any dict-like
        return {k: _deep_convert(v) for k, v in obj.items()}
    if isinstance(obj, (str, bytes)):  # strings are iterable – don't recurse
        return obj
    try:
        iter(obj)                      # RepeatedComposite or any list-like
        return [_deep_convert(item) for item in obj]
    except TypeError:
        return obj                     # scalar (int, float, bool, None, …)


def _extract_args(fc_args) -> Dict[str, Any]:
    """Deeply convert Gemini function_call.args to a plain Python dict.

    dict(fc_args) is a *shallow* conversion — nested arrays/objects stay as
    RepeatedComposite / MapComposite protobuf types which are not JSON-serialisable.
    _deep_convert walks the full tree and replaces every protobuf container with
    a plain list or dict.
    """
    try:
        return _deep_convert(fc_args)
    except Exception:
        return dict(fc_args)


class BaseAgent:
    """
    Wraps a single Gemini agentic loop:
      1. Start a chat with the system prompt + tools
      2. Send the user message
      3. If Gemini returns function_call parts, execute them all and loop
      4. Return final text response + any structured data collected
    """

    name: str = "BaseAgent"
    system_prompt: str = "You are a helpful AI assistant."
    tools: List[Dict[str, Any]] = []
    max_iterations: int = 10

    async def run(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Returns:
          { "reply": str, "tool_results": list, "structured_data": dict }
        """
        gemini_tools = _to_gemini_tools(self.tools)

        model_kwargs: Dict[str, Any] = {
            "model_name": MODEL,
            "system_instruction": self.system_prompt,
        }
        if gemini_tools:
            model_kwargs["tools"] = gemini_tools

        model = genai.GenerativeModel(**model_kwargs)

        # Convert history: Anthropic uses "assistant", Gemini uses "model"
        gemini_history = []
        for msg in (conversation_history or []):
            gemini_history.append({
                "role": "user" if msg["role"] == "user" else "model",
                "parts": [msg["content"]],
            })

        chat = model.start_chat(history=gemini_history)

        tool_results_collected: List[Dict] = []
        structured_data: Dict[str, Any] = {}

        response = chat.send_message(user_message)

        for _ in range(self.max_iterations):
            # Collect function call parts
            fn_call_parts = [
                p for p in response.parts
                if hasattr(p, "function_call") and p.function_call.name
            ]

            if not fn_call_parts:
                break  # No more tool calls → done

            # Execute all function calls, collect responses
            response_parts: List[protos.Part] = []
            for part in fn_call_parts:
                fc = part.function_call
                args = _extract_args(fc.args)
                result = await execute_tool(fc.name, args)
                tool_results_collected.append({"tool": fc.name, "result": result})
                if isinstance(result, dict):
                    structured_data.update(result)

                response_parts.append(
                    protos.Part(
                        function_response=protos.FunctionResponse(
                            name=fc.name,
                            response={"result": str(result)},
                        )
                    )
                )

            response = chat.send_message(response_parts)

        # Extract final text
        reply = "".join(
            p.text for p in response.parts if hasattr(p, "text") and p.text
        )

        return {
            "reply": reply or "I've processed your request.",
            "tool_results": tool_results_collected,
            "structured_data": structured_data,
        }
