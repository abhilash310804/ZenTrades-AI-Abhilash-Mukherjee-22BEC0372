"""
Pipeline A: Demo Call Transcript → Account Memo JSON + Agent Spec v1
Usage: python pipeline_a_extract.py --transcript <path> --account_id <id>
"""

import json
import os
import re
import sys
import argparse
from datetime import datetime
from pathlib import Path

# ── Anthropic Claude (free tier via claude.ai API) ──────────────────────────
# Uses the Anthropic API. Set ANTHROPIC_API_KEY in environment.
# Free tier: claude-haiku is cheapest; claude-3-5-haiku for speed.
# Zero-cost option: use local Ollama with llama3 instead (see --local flag).

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

EXTRACTION_PROMPT = """
You are a configuration extraction system for Clara Answers, an AI voice agent platform.

You will be given a demo call transcript between a Clara sales/onboarding team and a potential client.

Your job is to extract all relevant configuration data and output a single valid JSON object.

STRICT RULES:
- Only extract what is explicitly stated. Do NOT invent or assume details.
- If a field is missing, set its value to null or an empty array [].
- If something is unclear or ambiguous, add it to questions_or_unknowns.
- Output ONLY raw JSON — no markdown, no explanation, no preamble.

Extract into this exact schema:
{
  "company_name": string or null,
  "contact_name": string or null,
  "contact_email": string or null,
  "contact_phone": string or null,
  "notification_email": string or null,
  "notification_sms": string or null,
  "business_hours": {
    "days": array of strings,
    "start": "HH:MM" or null,
    "end": "HH:MM" or null,
    "timezone": string or null
  },
  "office_address": string or null,
  "services_supported": array of strings,
  "pricing": {
    "service_call_fee": number or null,
    "hourly_rate": number or null,
    "billing_increment": string or null,
    "notes": string or null
  },
  "emergency_definition": array of strings,
  "emergency_routing_rules": {
    "who_can_trigger_emergency": array of objects,
    "routing_logic": string or null,
    "transfer_to": string or null,
    "fallback_if_transfer_fails": string or null
  },
  "non_emergency_routing_rules": {
    "during_hours": string or null,
    "after_hours": string or null
  },
  "call_transfer_rules": {
    "transfer_number": string or null,
    "timeout": string or null,
    "retries": string or null,
    "transfer_fail_message": string or null
  },
  "integration_constraints": array of strings,
  "after_hours_flow_summary": string or null,
  "office_hours_flow_summary": string or null,
  "questions_or_unknowns": array of strings,
  "notes": string or null
}

TRANSCRIPT:
{transcript}
"""

AGENT_PROMPT_TEMPLATE = """
You are a prompt engineer for Clara Answers, an AI voice agent platform.

Given an Account Memo JSON, generate a production-ready system prompt for a Retell AI voice agent.

The prompt MUST include:
BUSINESS HOURS FLOW:
1. Greeting
2. Ask purpose of call
3. Collect name and callback number
4. Transfer to owner or route appropriately
5. Fallback if transfer fails
6. Ask if anything else needed
7. Close call

AFTER HOURS FLOW:
1. Greeting — state business hours
2. Ask purpose
3. Confirm if emergency
4. If emergency: collect name, number, address immediately → attempt transfer → fallback if fails
5. If non-emergency: collect name, number, message → confirm next-business-day follow-up
6. Ask if anything else needed
7. Close

RULES:
- Do NOT mention "function calls", tools, or internal systems to the caller
- Do NOT ask too many questions — only collect what is needed for routing/dispatch
- Be warm, concise, professional
- Include pricing info only if caller asks
- Output ONLY the system prompt text — no JSON wrapper, no explanation

ACCOUNT MEMO:
{memo}
"""


def extract_with_claude(transcript: str, api_key: str) -> dict:
    """Call Claude API to extract structured data from transcript."""
    client = anthropic.Anthropic(api_key=api_key)
    prompt = EXTRACTION_PROMPT.format(transcript=transcript)
    
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    raw = message.content[0].text.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$", "", raw)
    return json.loads(raw.strip())


def generate_prompt_with_claude(memo: dict, api_key: str) -> str:
    """Call Claude API to generate the agent system prompt."""
    client = anthropic.Anthropic(api_key=api_key)
    prompt = AGENT_PROMPT_TEMPLATE.format(memo=json.dumps(memo, indent=2))
    
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


def extract_rule_based(transcript: str) -> dict:
    """
    Zero-cost fallback: rule-based extraction using regex.
    Less powerful than LLM but requires no API calls.
    """
    memo = {
        "company_name": None,
        "contact_name": None,
        "contact_email": None,
        "contact_phone": None,
        "notification_email": None,
        "notification_sms": None,
        "business_hours": {"days": [], "start": None, "end": None, "timezone": None},
        "office_address": None,
        "services_supported": [],
        "pricing": {"service_call_fee": None, "hourly_rate": None, "billing_increment": None, "notes": None},
        "emergency_definition": [],
        "emergency_routing_rules": {
            "who_can_trigger_emergency": [],
            "routing_logic": None,
            "transfer_to": None,
            "fallback_if_transfer_fails": None
        },
        "non_emergency_routing_rules": {"during_hours": None, "after_hours": None},
        "call_transfer_rules": {"transfer_number": None, "timeout": None, "retries": None, "transfer_fail_message": None},
        "integration_constraints": [],
        "after_hours_flow_summary": None,
        "office_hours_flow_summary": None,
        "questions_or_unknowns": [],
        "notes": None
    }

    # Email
    emails = re.findall(r'[\w.+-]+@[\w-]+\.[a-z]{2,}', transcript, re.IGNORECASE)
    if emails:
        memo["contact_email"] = emails[0]
        memo["notification_email"] = emails[0]

    # Phone numbers (North American)
    phones = re.findall(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', transcript)
    if phones:
        memo["contact_phone"] = phones[0]

    # Business hours patterns
    hours_match = re.search(r'(\d+)\s*(?:to|till|until|-)\s*(\d+(?::\d+)?)', transcript, re.IGNORECASE)
    if hours_match:
        memo["business_hours"]["start"] = f"{hours_match.group(1)}:00"
        memo["business_hours"]["end"] = hours_match.group(2) if ':' in hours_match.group(2) else f"{hours_match.group(2)}:00"

    days_match = re.search(r'(Monday|Mon)\s+(?:to|through|-)\s+(Friday|Fri)', transcript, re.IGNORECASE)
    if days_match:
        memo["business_hours"]["days"] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    # Service call fee
    fee_match = re.search(r'\$(\d+)\s*(?:service call fee|call out|call-out)', transcript, re.IGNORECASE)
    if fee_match:
        memo["pricing"]["service_call_fee"] = int(fee_match.group(1))

    # Hourly rate
    hourly_match = re.search(r'\$(\d+)\s*(?:per hour|an hour|hourly)', transcript, re.IGNORECASE)
    if hourly_match:
        memo["pricing"]["hourly_rate"] = int(hourly_match.group(1))

    memo["questions_or_unknowns"].append("Rule-based extraction used — review all fields manually")
    return memo


def build_agent_spec(account_id: str, memo: dict, system_prompt: str) -> dict:
    """Build the full Retell Agent Spec JSON."""
    bh = memo.get("business_hours", {})
    days = ", ".join(bh.get("days", [])) or "UNKNOWN"
    start = bh.get("start", "UNKNOWN")
    end = bh.get("end", "UNKNOWN")
    tz = bh.get("timezone", "UNKNOWN")

    pricing = memo.get("pricing", {})
    transfer = memo.get("call_transfer_rules", {})

    return {
        "agent_name": f"Clara - {memo.get('company_name', 'Unknown Company')}",
        "version": "v1",
        "source": "demo_call",
        "account_id": account_id,
        "generated_at": datetime.now().strftime("%Y-%m-%d"),

        "voice_style": {
            "tone": "professional, warm, efficient",
            "language": "en-US",
            "persona": f"Clara, a helpful assistant for {memo.get('company_name', 'the company')}"
        },

        "key_variables": {
            "company_name": memo.get("company_name"),
            "owner_name": memo.get("contact_name"),
            "business_hours": f"{days}, {start} to {end}",
            "timezone": tz,
            "service_call_fee": f"${pricing.get('service_call_fee')}" if pricing.get("service_call_fee") else None,
            "hourly_rate": f"${pricing.get('hourly_rate')} per hour" if pricing.get("hourly_rate") else None,
            "notification_email": memo.get("notification_email"),
            "transfer_number": transfer.get("transfer_number", "PENDING")
        },

        "call_transfer_protocol": {
            "trigger": "Caller requests to speak with owner, or call requires immediate dispatch",
            "transfer_number": transfer.get("transfer_number", "PENDING"),
            "announce_before_transfer": "Please hold for just a moment while I connect you.",
            "timeout_seconds": transfer.get("timeout", "PENDING"),
            "on_transfer_fail": transfer.get("transfer_fail_message", "I'm sorry, they're unavailable. I've captured your details and someone will follow up shortly.")
        },

        "fallback_protocol": {
            "trigger": "Transfer fails or times out",
            "message": "I wasn't able to connect you directly, but I've noted your details and someone will be in touch shortly. Is there anything else I can help with?",
            "ensure_details_collected": True
        },

        "system_prompt": system_prompt,

        "tool_invocation_placeholders": {
            "transfer_call": "Trigger when caller should be connected to owner. Use transfer number from key_variables.",
            "send_notification": "After each call, send summary to notification_email and notification_sms with: caller name, number, purpose, timestamp, outcome."
        }
    }


def run_pipeline_a(transcript_path: str, account_id: str, output_dir: str, use_llm: bool = True):
    """Main Pipeline A runner."""
    print(f"\n{'='*60}")
    print(f"PIPELINE A — Demo Call → Agent Spec v1")
    print(f"Account ID : {account_id}")
    print(f"Transcript : {transcript_path}")
    print(f"{'='*60}\n")

    # Read transcript
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = f.read()
    print(f"✓ Transcript loaded ({len(transcript)} chars)")

    # Extract memo
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if use_llm and ANTHROPIC_AVAILABLE and api_key:
        print("✓ Extracting with Claude API...")
        memo = extract_with_claude(transcript, api_key)
    else:
        print("⚠ Using rule-based extraction (no API key found)")
        memo = extract_rule_based(transcript)

    # Add metadata
    memo["account_id"] = account_id
    memo["version"] = "v1"
    memo["source"] = "demo_call"
    memo["generated_at"] = datetime.now().strftime("%Y-%m-%d")

    # Save memo
    out = Path(output_dir) / account_id / "v1"
    out.mkdir(parents=True, exist_ok=True)

    memo_path = out / "account_memo.json"
    with open(memo_path, "w") as f:
        json.dump(memo, f, indent=2)
    print(f"✓ Account memo saved: {memo_path}")

    # Generate system prompt
    if use_llm and ANTHROPIC_AVAILABLE and api_key:
        print("✓ Generating agent system prompt with Claude API...")
        system_prompt = generate_prompt_with_claude(memo, api_key)
    else:
        system_prompt = "[SYSTEM PROMPT — run with ANTHROPIC_API_KEY set to generate automatically]"

    # Build + save agent spec
    spec = build_agent_spec(account_id, memo, system_prompt)
    spec_path = out / "agent_spec.json"
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2)
    print(f"✓ Agent spec saved: {spec_path}")

    # Log unknowns
    unknowns = memo.get("questions_or_unknowns", [])
    if unknowns:
        print(f"\n⚠ OPEN QUESTIONS ({len(unknowns)}):")
        for q in unknowns:
            print(f"  - {q}")

    print(f"\n✅ Pipeline A complete for {account_id}")
    return memo, spec


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clara Pipeline A: Demo → Agent Spec v1")
    parser.add_argument("--transcript", required=True, help="Path to transcript .txt file")
    parser.add_argument("--account_id", required=True, help="Unique account ID e.g. BEN001")
    parser.add_argument("--output_dir", default="outputs/accounts", help="Output directory")
    parser.add_argument("--no-llm", action="store_true", help="Use rule-based extraction only")
    args = parser.parse_args()

    run_pipeline_a(
        transcript_path=args.transcript,
        account_id=args.account_id,
        output_dir=args.output_dir,
        use_llm=not args.no_llm
    )
