"""
Token Cost Accounting and AGENTS.md Execution Logging Engine.
Tracks LLM usage metrics and generates evaluation/usage_report.md & log.txt.
"""

import os
from datetime import datetime
from typing import Dict, List


class TokenTracker:
    def __init__(self, log_path: str = "log.txt", usage_report_path: str = "evaluation/usage_report.md"):
        self.log_path = log_path
        self.usage_report_path = usage_report_path
        self.usage_history: List[Dict] = []
        
        # Ensure evaluation directory exists
        os.makedirs(os.path.dirname(usage_report_path), exist_ok=True)

    def log_agent_turn(self, agent_name: str, action: str, details: str):
        """Appends agent turns to log.txt per AGENTS.md guidelines."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{agent_name}] {action}: {details}\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def record_llm_call(
        self,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        purpose: str,
        estimated_cost: float = 0.0,
    ):
        """Records an LLM call metric for token reporting."""
        self.usage_history.append({
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "model_name": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "purpose": purpose,
            "cost": estimated_cost,
        })

    def generate_usage_report(self):
        """Generates evaluation/usage_report.md."""
        total_calls = len(self.usage_history)
        total_input = sum(u["input_tokens"] for u in self.usage_history)
        total_output = sum(u["output_tokens"] for u in self.usage_history)
        total_cost = sum(u["cost"] for u in self.usage_history)

        report_content = f"""# LLM Token Usage & Cost Report

## Usage Summary
- **Total API Calls:** {total_calls}
- **Total Input Tokens:** {total_input}
- **Total Output Tokens:** {total_output}
- **Total Estimated Cost (USD):** ${total_cost:.6f}

## Detailed Call Breakdown
| Timestamp | Provider | Model | Purpose | Input Tokens | Output Tokens | Cost ($) |
|---|---|---|---|---|---|---|
"""
        for item in self.usage_history:
            report_content += (
                f"| {item['timestamp']} | {item['provider']} | {item['model_name']} | "
                f"{item['purpose']} | {item['input_tokens']} | {item['output_tokens']} | ${item['cost']:.6f} |\n"
            )

        with open(self.usage_report_path, "w", encoding="utf-8") as f:
            f.write(report_content)