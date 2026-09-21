# Curate Analytics Outreach Automation Pipeline

A daily-runnable Python agent pipeline that discovers ~100 B2B implementation-partner candidates per run from Clutch.co, qualifies them with DeepSeek LLM, enriches/verifies contacts via Hunter.io, drafts personalized emails, sends via SMTP, and manages opt-outs/follow-ups while maintaining CASL compliance.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up environment

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Then edit `.env` with:
- `APIFY_API_TOKEN`: Your Apify API token (for the Clutch scraper actor)
- `HUNTER_API_KEY`: Hunter.io API key
- `DEEPSEEK_API_KEY`: DeepSeek API key
- `EMAIL_ADDRESS`: outreach@curateanalytics.ca (Titan Email)
- `EMAIL_APP_PASSWORD`: Your Titan Email app password

### 3. Configure the pipeline

Edit `config.yaml`:
- Set `discovery.actor_id` to your Clutch-scraping Apify actor ID (e.g., `username/clutch-scraper`)
- Review other settings (daily_target, competitor list, decision-maker titles, Hunter quotas, etc.)

### 4. Initialize the workbook

```bash
python -m outreach_agent.cli init-workbook
```

This creates `data/partner_pipeline.xlsx` with all 4 tabs (Leads_Source, Partner_Tracker, Suppression_List, Audit_Log) and headers.

## Pipeline Overview

The pipeline consists of 9 stages, each independently runnable:

| Stage | Description | Status | Notes |
|-------|-------------|--------|-------|
| **discover** | Fetch companies from Clutch via Apify actor | `new` → `qualified`/`rejected` | Daily round-robin category rotation, deduped by domain |
| **qualify** | Evaluate with DeepSeek LLM | `new` → `qualified`/`rejected` | Competitor name pre-filter, append to Partner_Tracker |
| **enrich** | Find decision-makers via Hunter Domain Search | `qualified` → `enriched`/`no_contact_found` | Checks monthly search quota, halts if exhausted |
| **verify** | Validate emails via Hunter Email Verifier | `enriched` → `verified`/`email_invalid` | Checks verification quota, halts if exhausted |
| **draft** | Generate personalized email via DeepSeek | `verified` → `drafted` | Validates subject line if required in config |
| **send** | Deliver emails via SMTP (Titan) | `drafted` → `pending_approval`/`sent` | Hard gate: suppression check always applied. Manual approval gate when `require_manual_approval: true` |
| **followup** | Send follow-ups for non-responsive leads | `sent` → `followup1_sent` → `followup2_sent`/`exhausted` | Respects day thresholds and max follow-ups config |
| **optout-poll** | Check inbox for unsubscribe/bounce replies via IMAP | updates `responded`, `opted_out`, `invalid` status | Runs repeatedly on schedule (30-min default) |

## Running stages

### Sequential run (typical daily schedule)

```bash
python -m outreach_agent.cli discover
python -m outreach_agent.cli qualify
python -m outreach_agent.cli enrich
python -m outreach_agent.cli verify
python -m outreach_agent.cli draft
python -m outreach_agent.cli send
python -m outreach_agent.cli followup
```

### With options

```bash
# Dry run (no Excel writes)
python -m outreach_agent.cli discover --dry-run

# Limit rows processed (useful for testing)
python -m outreach_agent.cli qualify --limit 5

# Approve and send all pending emails (use with caution!)
python -m outreach_agent.cli send --approve-all-pending
```

### Repeated polling stage

```bash
# Run repeatedly on a schedule (via Task Scheduler, cron, or manually)
python -m outreach_agent.cli optout-poll
```

## Manual Approval Gate

When `outreach.require_manual_approval: true` (default):

1. `send` stage **does not send** — instead, it generates `review/review_<run_id>.csv` with draft subjects and body previews
2. **Human review**: Open the CSV or Excel workbook (Partner_Tracker tab)
3. **To approve**: Edit Partner_Tracker, set `status = "approved"` for rows you want to send
4. **Re-run send**: `python -m outreach_agent.cli send` picks up `status == "approved"` rows and sends them (still checks suppression first — hard gate)
5. Same process for follow-ups: `pending_action` column shows which follow-up stage (initial/followup1/followup2)

## Workbook structure

- **Leads_Source**: Append-only ledger of all discovered companies. Status transitions: `new` → `qualified` | `rejected`
- **Partner_Tracker**: Working set of qualified leads through enrichment, verification, send, and follow-ups
- **Suppression_List**: Opt-outs, bounces, and other suppressed emails/domains (hard gate — no exceptions)
- **Audit_Log**: Mirror of key decisions logged to `data/audit_log.jsonl` (JSONL is authoritative, Excel is best-effort)

## Data flow and idempotency

- Every stage filters on a specific input status (`new`, `qualified`, `enriched`, etc.), so re-running never reprocesses rows
- Status only advances on success; failed rows keep their status and are retried next run — **no separate retry queue**
- Deduplication by domain (discover stage) prevents duplicate lead insertion
- Suppression check (send/followup stages) is **always** applied — no bypass
- IMAP polling uses UID-based high-water marking (`state/imap_last_uid.json`), not `\Seen` flags, for robustness

## Hunter.io quota management

- Local counters in `state/hunter_usage.json` (seeded from `config.yaml`'s `hunter_limits.verifications_used` on first run)
- Before each enrich/verify call, quotas are checked; if at/over limit, the stage halts with a warning and remaining rows keep their status (picked up next run after quota resets)
- Monthly search quota rolls over on calendar month change (tracked in `month_key`)

## Audit logging

- **JSONL (authoritative)**: `data/audit_log.jsonl` — one line per decision, human-readable, machine-parseable
- **Excel mirror**: Audit_Log tab — best-effort, non-fatal failures (if Excel write fails, JSONL succeeded)
- Every run prints a `run_id` (UUID); use it to grep audit log and reconstruct all operations from one invocation

## Suppression & CASL compliance

- Opt-outs are processed within 30 minutes (default `opt_out.poll_interval_minutes`)
- On opt-out detection (keyword match or LLM classification), the email **and domain** are added to Suppression_List
- Both send and followup stages re-check Suppression_List fresh before sending — hard gate, no exceptions
- `responded` status halts automation (manual handoff); mark escalations/genuine interest manually

## Configuration reference

See `config.yaml` for all settings:

- `discovery.categories`: List of Clutch category URLs to rotate through
- `discovery.daily_target`: Max leads per day (100 default)
- `discovery.actor_id`: **Must be filled in** — your Apify actor ID
- `qualification.exclude_competitors`: Competitor name blacklist
- `qualification.exclude_type`: Exclude MSP or other type
- `enrichment.decision_maker_titles`: Titles to filter on (case-insensitive substring match)
- `hunter_limits`: Monthly search quota, total verification quota, and current usage
- `outreach.sender_line`, `outreach.require_subject_line`, `outreach.require_manual_approval`: Email config
- `outreach.smtp_host`, `smtp_port`, `imap_host`, `imap_port`: Mail server (pre-filled for Titan Email)
- `follow_up.days_before_first_followup`, `days_before_second_followup`, `max_follow_ups`: Timing and limits
- `opt_out.poll_interval_minutes`, `keyword_triggers`: Polling cadence and unsubscribe keywords

## Testing without live API keys

```bash
# All unit tests (no network)
pytest tests/

# Specific test file
pytest tests/test_excel_store.py -v
```

Tests cover:
- Excel read/write round-trips and atomic save
- Domain/email normalization and deduplication
- HTTP clients with mocked responses (success, retry, auth errors)
- Status transitions per stage against synthetic data
- Full offline pipeline smoke test
- Suppression checks (verified emails are never sent if suppressed)

## Troubleshooting

**"Config file not found"**
- Ensure `config.yaml` exists in the current directory

**"Missing required environment variables"**
- Check `.env` is in the project root and all required keys are filled in
- Verify `APIFY_API_TOKEN`, `HUNTER_API_KEY`, `DEEPSEEK_API_KEY`, `EMAIL_APP_PASSWORD` are set

**"Excel file appears to be open in Excel"**
- Close the `partner_pipeline.xlsx` file before running a stage
- The pipeline writes atomically (to a `.tmp` file first), but can't write while the file is locked

**"Hunter quota exceeded"**
- Check `state/hunter_usage.json` and compare against `config.yaml`'s max limits
- Monthly search quota resets on the first of the month
- Consider reducing `daily_target` or increasing `hunter_limits.max_searches_per_month`

**"No emails in review/review_<run_id>.csv after send stage"**
- This is normal if `require_manual_approval: false` — emails are sent directly instead
- If `require_manual_approval: true`, check that there are rows at `status == drafted`

**"IMAP poll returns no messages"**
- Ensure `imap_last_uid.json` isn't stale; delete it to rescan the inbox on the next poll
- Check that the mailbox actually has replies (test by sending a test email)

## Scheduling

Suggested cadence (Windows Task Scheduler or cron):

- **Daily** (e.g., 9 AM): `discover → qualify → enrich → verify → draft → send → followup`
- **Every 30 minutes**: `optout-poll` (for CASL compliance)

Example Windows Task Scheduler batch file:

```batch
cd C:\Users\...\Outreach_Automation
python -m outreach_agent.cli discover
python -m outreach_agent.cli qualify
python -m outreach_agent.cli enrich
python -m outreach_agent.cli verify
python -m outreach_agent.cli draft
python -m outreach_agent.cli send
python -m outreach_agent.cli followup
```

Example cron (Linux):

```cron
0 9 * * * cd /path/to/Outreach_Automation && python -m outreach_agent.cli discover && python -m outreach_agent.cli qualify && ...

*/30 * * * * cd /path/to/Outreach_Automation && python -m outreach_agent.cli optout-poll
```

## API key rotation

If an API key expires or is revoked:
1. Update `.env`
2. The stage that uses that key will fail with a clear `NonRetriableAPIError` and abort (exit code 1)
3. Fix the key and re-run; rows keep their status and are retried next run

## License

Internal use by Curate Analytics
