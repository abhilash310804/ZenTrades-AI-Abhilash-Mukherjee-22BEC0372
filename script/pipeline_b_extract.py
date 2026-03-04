"""
Pipeline B: Onboarding Call/Form → Account Memo v2 + Agent Spec v2 + Changelog
Usage: python pipeline_b_update.py --onboarding <path> --account_id <id> --type [transcript|form]
"""

import json
import os
import re
import argparse
from datetime import datetime
from pathlib import Path
from copy import deepcopy

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

ONBOARDING_EXTRACTION_PROMPT = """
You are a configuration update system for Clara Answers, an AI voice agent platform.

You will be given:
1. An existing Account Memo JSON (v1, from a demo call)
2. An onboarding call transcript OR onboarding form data

Your job is to extract ONLY the new or updated information from the onboarding source, then output a JSON "patch" — just the fields that changed or were confirmed/clarified.

STRICT RULES:
- Only extract what is EXPLICITLY stated in the onboarding source.
- Do NOT copy fields from v1 unless they are being updated.
- If a field is confirmed unchanged, note it in "confirmed_unchanged".
- If a field conflicts with v1, add it to "conflicts".
- Output ONLY raw JSON — no markdown, no explanation.

Output schema:
{
  "updates": {
    <only the fields that changed, using same schema as account_memo>
  },
  "confirmed_unchanged": [list of field names that were explicitly confirmed as unchanged],
  "conflicts": [
    {
      "field": "field name",
      "v1_value": "...",
      "onboarding_value": "...",
      "resolution": "use onboarding value / keep v1 / flag for manual review"
    }
  ],
  "new_information": [list of things mentioned in onboarding not in v1 at all],
  "questions_resolved": [list of questions_or_unknowns from v1 that are now answered],
  "questions_remaining": [list of questions still unresolved or newly raised]
}

EXISTING V1 MEMO:
{v1_memo}

ONBOARDING SOURCE:
{onboarding_data}
"""


def apply_patch(v1_memo: dict, patch: dict) -> dict:
    """Deep merge patch updates into v1 memo to produce v2."""
    v2 = deepcopy(v1_memo)
    updates = patch.get("updates", {})

    def deep_merge(base, override):
        for key, val in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(val, dict):
                deep_merge(base[key], val)
            else:
                base[key] = val

    deep_merge(v2, updates)

    # Update version metadata
    v2["version"] = "v2"
    v2["source"] = "onboarding"
    v2["generated_at"] = datetime.now().strftime("%Y-%m-%d")

    # Update unknowns list
    resolved = patch.get("questions_resolved", [])
    remaining = patch.get("questions_remaining", [])
    original_unknowns = v1_memo.get("questions_or_unknowns", [])
    new_unknowns = [q for q in original_unknowns if not any(r.lower() in q.lower() for r in resolved)]
    new_unknowns.extend(remaining)
    v2["questions_or_unknowns"] = list(set(new_unknowns))

    return v2


def build_changelog(v1_memo: dict, v2_memo: dict, patch: dict, account_id: str) -> dict:
    """Generate a structured changelog between v1 and v2."""
    changes = []

    updates = patch.get("updates", {})
    for field, new_val in updates.items():
        old_val = v1_memo.get(field)
        if old_val != new_val:
            changes.append({
                "field": field,
                "change_type": "updated" if old_val is not None else "added",
                "v1_value": old_val,
                "v2_value": new_val
            })

    return {
        "account_id": account_id,
        "changelog_generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "v1_source": "demo_call",
        "v2_source": "onboarding",
        "total_changes": len(changes),
        "changes": changes,
        "conflicts": patch.get("conflicts", []),
        "questions_resolved": patch.get("questions_resolved", []),
        "questions_remaining": v2_memo.get("questions_or_unknowns", []),
        "new_information": patch.get("new_information", [])
    }


def extract_onboarding_patch(v1_memo: dict, onboarding_data: str, api_key: str) -> dict:
    """Use Claude to extract updates from onboarding."""
    client = anthropic.Anthropic(api_key=api_key)
    prompt = ONBOARDING_EXTRACTION_PROMPT.format(
        v1_memo=json.dumps(v1_memo, indent=2),
        onboarding_data=onboarding_data
    )
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$", "", raw)
    return json.loads(raw.strip())


def generate_updated_prompt(memo: dict, api_key: str) -> str:
    """Regenerate the agent system prompt from v2 memo."""
    from pipeline_a_extract import generate_prompt_with_claude
    return generate_prompt_with_claude(memo, api_key)


def run_pipeline_b(onboarding_path: str, account_id: str, output_dir: str, input_type: str = "transcript"):
    """Main Pipeline B runner."""
    print(f"\n{'='*60}")
    print(f"PIPELINE B — Onboarding → Agent Spec v2")
    print(f"Account ID  : {account_id}")
    print(f"Onboarding  : {onboarding_path}")
    print(f"Input type  : {input_type}")
    print(f"{'='*60}\n")

    base = Path(output_dir) / account_id

    # Load v1 memo
    v1_path = base / "v1" / "account_memo.json"
    if not v1_path.exists():
        print(f"❌ v1 account memo not found at {v1_path}")
        print("   Run Pipeline A first.")
        return

    with open(v1_path) as f:
        v1_memo = json.load(f)
    print(f"✓ v1 memo loaded")

    # Load v1 agent spec
    v1_spec_path = base / "v1" / "agent_spec.json"
    with open(v1_spec_path) as f:
        v1_spec = json.load(f)

    # Load onboarding input
    with open(onboarding_path, "r", encoding="utf-8") as f:
        onboarding_data = f.read()
    print(f"✓ Onboarding data loaded ({len(onboarding_data)} chars)")

    # Extract patch
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if ANTHROPIC_AVAILABLE and api_key:
        print("✓ Extracting updates with Claude API...")
        patch = extract_onboarding_patch(v1_memo, onboarding_data, api_key)
    else:
        print("⚠ No API key — manual patch required")
        patch = {"updates": {}, "confirmed_unchanged": [], "conflicts": [], "new_information": [], "questions_resolved": [], "questions_remaining": []}

    # Build v2 memo
    v2_memo = apply_patch(v1_memo, patch)

    # Build changelog
    changelog = build_changelog(v1_memo, v2_memo, patch, account_id)

    # Regenerate system prompt
    if ANTHROPIC_AVAILABLE and api_key:
        print("✓ Regenerating agent prompt...")
        system_prompt = generate_updated_prompt(v2_memo, api_key)
    else:
        system_prompt = v1_spec.get("system_prompt", "[REGENERATE WITH API KEY]")

    # Build v2 agent spec
    from pipeline_a_extract import build_agent_spec
    v2_spec = build_agent_spec(account_id, v2_memo, system_prompt)
    v2_spec["version"] = "v2"
    v2_spec["source"] = "onboarding"

    # Save outputs
    v2_dir = base / "v2"
    v2_dir.mkdir(parents=True, exist_ok=True)

    with open(v2_dir / "account_memo.json", "w") as f:
        json.dump(v2_memo, f, indent=2)
    print(f"✓ v2 account memo saved")

    with open(v2_dir / "agent_spec.json", "w") as f:
        json.dump(v2_spec, f, indent=2)
    print(f"✓ v2 agent spec saved")

    changelog_path = base / "changelog.json"
    with open(changelog_path, "w") as f:
        json.dump(changelog, f, indent=2)
    print(f"✓ Changelog saved: {changelog_path}")

    # Print summary
    print(f"\n📋 CHANGELOG SUMMARY:")
    print(f"   Total changes  : {changelog['total_changes']}")
    print(f"   Conflicts      : {len(changelog['conflicts'])}")
    print(f"   Q's resolved   : {len(changelog['questions_resolved'])}")
    print(f"   Q's remaining  : {len(changelog['questions_remaining'])}")

    if changelog["conflicts"]:
        print(f"\n⚠ CONFLICTS TO REVIEW:")
        for c in changelog["conflicts"]:
            print(f"  - {c['field']}: v1={c['v1_value']} | onboarding={c['onboarding_value']}")

    print(f"\n✅ Pipeline B complete for {account_id}")
    return v2_memo, v2_spec, changelog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clara Pipeline B: Onboarding → Agent Spec v2")
    parser.add_argument("--onboarding", required=True, help="Path to onboarding transcript or form JSON")
    parser.add_argument("--account_id", required=True, help="Account ID e.g. BEN001")
    parser.add_argument("--output_dir", default="outputs/accounts", help="Output base directory")
    parser.add_argument("--type", default="transcript", choices=["transcript", "form"], help="Input type")
    args = parser.parse_args()

    run_pipeline_b(
        onboarding_path=args.onboarding,
        account_id=args.account_id,
        output_dir=args.output_dir,
        input_type=args.type
    )
