"""
Perception Extractor Module for Buy or Wait? Autonomous Financial AI Engine.
Uses LLMs to parse unstructured user messages into structured spending adjustments.
"""

import json
import os
from typing import Optional
from pydantic import BaseModel, Field
from openai import OpenAI

from code.credentials import CredentialsManager


class MessageExtractionResult(BaseModel):
    """Structured extraction target for message processing."""
    event_id: Optional[str] = Field(default=None, description="Target financial event ID")
    is_cancelled: bool = Field(default=False, description="True if the user cancelled or stopped this event")
    new_flexible_amount: Optional[float] = Field(default=None, description="New reduced/increased amount if modified")
    reasoning: str = Field(default="", description="Brief extraction rationale")


class PerceptionExtractor:
    def __init__(self, text_model: str = "llama-3.1-70b-versatile"):
        self.credentials = CredentialsManager()
        self.text_model = text_model
        
        # Instantiate OpenAI client configured for Groq endpoint
        api_key = os.getenv("GROQ_API_KEY") or getattr(self.credentials, "groq_api_key", None) or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        
        self.client = OpenAI(
            api_key=api_key if api_key else "dummy-key-for-fallback",
            base_url=base_url
        )

    def extract_message_updates(self, message_text: str, target_event_id: str) -> MessageExtractionResult:
        """
        Parses user text messages to determine if an event was cancelled or its flexible amount was modified.
        """
        prompt = f"""You are a financial perception extraction model.
Analyze the following user message regarding financial event '{target_event_id}':

Message: "{message_text}"

Return ONLY a valid JSON object matching this schema:
{{
  "event_id": "{target_event_id}",
  "is_cancelled": true/false,
  "new_flexible_amount": float or null,
  "reasoning": "short explanation"
}}
"""

        try:
            response = self.client.chat.completions.create(
                model=self.text_model,
                messages=[
                    {"role": "system", "content": "You are a precise financial data extraction assistant that outputs strict JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                response_format={"type": "json_object"} if "llama-3" in self.text_model or "gpt" in self.text_model else None
            )

            raw_content = response.choices[0].message.content.strip()
            data = json.loads(raw_content)

            return MessageExtractionResult(
                event_id=target_event_id,
                is_cancelled=bool(data.get("is_cancelled", False)),
                new_flexible_amount=float(data["new_flexible_amount"]) if data.get("new_flexible_amount") is not None else None,
                reasoning=str(data.get("reasoning", ""))
            )

        except Exception as e:
            # Fallback heuristic matching if API call fails or encounters issues
            lower_msg = message_text.lower()
            is_cancelled = any(w in lower_msg for w in ["cancel", "stop", "paused", "end", "terminated", "no longer"])
            
            return MessageExtractionResult(
                event_id=target_event_id,
                is_cancelled=is_cancelled,
                new_flexible_amount=None,
                reasoning=f"Fallback heuristic used due to API execution state: {str(e)}"
            )