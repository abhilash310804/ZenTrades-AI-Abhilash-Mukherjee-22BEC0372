Architecture & Data Flow

Demo Transcript (.txt)
        │
        ▼
[Pipeline A: pipeline_a_extract.py]
        │
        ├── LLM Extraction (Claude API) or Rule-Based Fallback
        │
        ├── Account Memo JSON (v1)          → outputs/accounts/<id>/v1/account_memo.json
        └── Retell Agent Spec JSON (v1)     → outputs/accounts/<id>/v1/agent_spec.json

Onboarding Transcript or Form (.txt / .json)
        │
        ▼
[Pipeline B: pipeline_b_update.py]
        │
        ├── Load v1 memo
        ├── LLM Patch Extraction
        ├── Deep merge → v2 memo
        ├── Regenerate agent prompt
        │
        ├── Account Memo JSON (v2)          → outputs/accounts/<id>/v2/account_memo.json
        ├── Retell Agent Spec JSON (v2)     → outputs/accounts/<id>/v2/agent_spec.json
        └── Changelog                       → outputs/accounts/<id>/changelog.json

All accounts at once:
[batch_run.py] → iterates dataset/ folder → runs Pipeline A + B per account

## File Structure

clara-pipeline/
├── scripts/
│   ├── pipeline_a_extract.py     # Demo transcript → v1 memo + agent spec
│   ├── pipeline_b_update.py      # Onboarding → v2 memo + agent spec + changelog
│   └── batch_run.py              # Batch runner for full dataset
├── workflows/
│   └── clara_n8n_workflow.json   # n8n workflow export (importable)
├── outputs/
│   └── accounts/
│       └── <account_id>/
│           ├── v1/
│           │   ├── account_memo.json
│           │   └── agent_spec.json
│           ├── v2/
│           │   ├── account_memo.json
│           │   └── agent_spec.json
│           └── changelog.json
├── dataset/
│   └── <account_id>/
│       ├── demo_transcript.txt
│       ├── onboarding_transcript.txt   (or)
│       └── onboarding_form.json
└── README.md

## Setup

### 1. Install dependencies

```bash
pip install anthropic
```

### 2. Set API key (zero-cost: use Claude free tier)

```bash
export ANTHROPIC_API_KEY=your_key_here
```

> **Zero-cost note:** The pipeline uses `claude-haiku-4-5-20251001` — the cheapest Claude model.
> For truly zero-cost, omit the API key and use `--no-llm` flag for rule-based extraction only.

### 3. Prepare dataset

```
dataset/
  BEN001/
    demo_transcript.txt
    onboarding_transcript.txt
  ACM002/
    demo_transcript.txt
    onboarding_form.json
```

---

## Running the Pipeline

### Single account — Pipeline A (demo only)

```bash
python scripts/pipeline_a_extract.py \
  --transcript dataset/BEN001/demo_transcript.txt \
  --account_id BEN001
```

### Single account — Pipeline B (onboarding update)

```bash
python scripts/pipeline_b_update.py \
  --onboarding dataset/BEN001/onboarding_transcript.txt \
  --account_id BEN001 \
  --type transcript
```

### Full dataset batch

```bash
python scripts/batch_run.py --dataset_dir dataset --output_dir outputs/accounts
```

### Rule-based only (no API key needed)

```bash
python scripts/pipeline_a_extract.py \
  --transcript dataset/BEN001/demo_transcript.txt \
  --account_id BEN001 \
  --no-llm
```

---

## n8n Workflow Setup

1. Install n8n locally via Docker:
   ```bash
   docker run -it --rm \
     -p 5678:5678 \
     -e N8N_BASIC_AUTH_ACTIVE=true \
     -e N8N_BASIC_AUTH_USER=admin \
     -e N8N_BASIC_AUTH_PASSWORD=password \
     -e ANTHROPIC_API_KEY=your_key \
     -v ~/.n8n:/home/node/.n8n \
     n8nio/n8n
   ```

2. Open `http://localhost:5678`

3. Import workflow: **Settings → Import from file** → select `workflows/clara_n8n_workflow.json`

4. Trigger Pipeline A:
   ```bash
   curl -X POST http://localhost:5678/webhook/pipeline-a \
     -H "Content-Type: application/json" \
     -d '{"account_id": "BEN001", "transcript": "..."}'
   ```

5. Trigger Pipeline B:
   ```bash
   curl -X POST http://localhost:5678/webhook/pipeline-b \
     -H "Content-Type: application/json" \
     -d '{"account_id": "BEN001", "data": "...", "input_type": "transcript"}'
   ```

## Retell Agent Setup (Manual Import)

Since Retell's API may require a paid plan:

1. Open `outputs/accounts/<id>/v1/agent_spec.json`
2. Log into [retell.ai](https://retell.ai)
3. Create a new agent
4. Copy the `system_prompt` field into the agent's system prompt
5. Set voice style to match `voice_style` in the spec
6. Configure call transfer number from `key_variables.transfer_number`
7. Set up post-call webhooks for notifications

## Output Formats

### Account Memo JSON
Key fields:
- `account_id`, `version`, `company_name`, `contact_*`
- `business_hours` (days, start, end, timezone)
- `emergency_definition`, `emergency_routing_rules`
- `call_transfer_rules`, `integration_constraints`
- `questions_or_unknowns` — explicitly flagged gaps

### Agent Spec JSON
Key fields:
- `agent_name`, `voice_style`, `system_prompt`
- `key_variables` (hours, timezone, pricing, transfer number)
- `call_transfer_protocol`, `fallback_protocol`
- `tool_invocation_placeholders`

### Changelog JSON
- `changes[]` — field-by-field diff (v1 → v2)
- `conflicts[]` — contradictions between demo and onboarding
- `questions_resolved[]` — unknowns now answered
- `questions_remaining[]` — still open

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Optional | Claude API key for LLM extraction |

## Known Limitations

- Transcripts must be clean text (no timestamps required but helps accuracy)
- Rule-based extraction (`--no-llm`) has lower accuracy for complex routing logic
- n8n file write nodes require filesystem access configuration
- Retell API integration is mocked — manual import step required if API is paywalled
- Batch runner processes accounts sequentially (not parallelized)

## What Would Be Improved With Production Access

- Retell API integration for programmatic agent creation/update
- Whisper API or AssemblyAI for audio transcription step
- Supabase for persistent structured storage with account history
- Asana/Linear API for automatic task creation per onboarding
- Parallel batch processing with async runners
- Webhook receiver for real-time onboarding form submissions
- Diff viewer UI (web dashboard)

---

## Sample Data

See `outputs/accounts/BEN001/` for a fully worked example based on the demo call with Ben's Electric Solutions (March 4, 2026).
