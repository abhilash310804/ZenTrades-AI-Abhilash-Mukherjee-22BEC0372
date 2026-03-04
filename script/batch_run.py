"""
Batch Runner: Process all demo + onboarding transcripts in the dataset directory.
Usage: python batch_run.py --dataset_dir <path>

Expected dataset structure:
  dataset/
    <account_id>/
      demo_transcript.txt
      onboarding_transcript.txt   (optional)
      onboarding_form.json        (optional, alternative to transcript)

Outputs go to: outputs/accounts/<account_id>/v1 and v2
"""

import os
import json
import argparse
from pathlib import Path
from datetime import datetime

# Add scripts dir to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from pipeline_a_extract import run_pipeline_a
from pipeline_b_update import run_pipeline_b

BATCH_LOG = []


def process_account(account_dir: Path, output_dir: str):
    account_id = account_dir.name
    result = {
        "account_id": account_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pipeline_a": "skipped",
        "pipeline_b": "skipped",
        "errors": []
    }

    # Pipeline A — Demo transcript
    demo_path = account_dir / "demo_transcript.txt"
    if demo_path.exists():
        try:
            run_pipeline_a(str(demo_path), account_id, output_dir)
            result["pipeline_a"] = "success"
        except Exception as e:
            result["pipeline_a"] = "failed"
            result["errors"].append(f"Pipeline A error: {str(e)}")
    else:
        result["errors"].append("No demo_transcript.txt found")

    # Pipeline B — Onboarding (transcript or form)
    onboarding_transcript = account_dir / "onboarding_transcript.txt"
    onboarding_form = account_dir / "onboarding_form.json"

    if onboarding_transcript.exists():
        try:
            run_pipeline_b(str(onboarding_transcript), account_id, output_dir, input_type="transcript")
            result["pipeline_b"] = "success"
        except Exception as e:
            result["pipeline_b"] = "failed"
            result["errors"].append(f"Pipeline B (transcript) error: {str(e)}")
    elif onboarding_form.exists():
        try:
            run_pipeline_b(str(onboarding_form), account_id, output_dir, input_type="form")
            result["pipeline_b"] = "success"
        except Exception as e:
            result["pipeline_b"] = "failed"
            result["errors"].append(f"Pipeline B (form) error: {str(e)}")
    else:
        result["pipeline_b"] = "no_onboarding_data"

    BATCH_LOG.append(result)
    return result


def run_batch(dataset_dir: str, output_dir: str):
    dataset = Path(dataset_dir)
    if not dataset.exists():
        print(f"❌ Dataset directory not found: {dataset_dir}")
        return

    accounts = [d for d in sorted(dataset.iterdir()) if d.is_dir()]
    print(f"\n{'='*60}")
    print(f"CLARA BATCH RUNNER")
    print(f"Dataset   : {dataset_dir}")
    print(f"Accounts  : {len(accounts)}")
    print(f"Output    : {output_dir}")
    print(f"{'='*60}\n")

    for account_dir in accounts:
        print(f"\n--- Processing: {account_dir.name} ---")
        process_account(account_dir, output_dir)

    # Save batch log
    log_path = Path(output_dir) / "batch_run_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(BATCH_LOG, f, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE — SUMMARY")
    print(f"{'='*60}")
    total = len(BATCH_LOG)
    a_ok = sum(1 for r in BATCH_LOG if r["pipeline_a"] == "success")
    b_ok = sum(1 for r in BATCH_LOG if r["pipeline_b"] == "success")
    print(f"  Accounts processed : {total}")
    print(f"  Pipeline A success : {a_ok}/{total}")
    print(f"  Pipeline B success : {b_ok}/{total}")
    print(f"  Batch log saved    : {log_path}")

    errors = [(r["account_id"], e) for r in BATCH_LOG for e in r["errors"]]
    if errors:
        print(f"\n⚠ ERRORS:")
        for acc, err in errors:
            print(f"  [{acc}] {err}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clara Batch Runner")
    parser.add_argument("--dataset_dir", default="dataset", help="Path to dataset directory")
    parser.add_argument("--output_dir", default="outputs/accounts", help="Output base directory")
    args = parser.parse_args()

    run_batch(args.dataset_dir, args.output_dir)
