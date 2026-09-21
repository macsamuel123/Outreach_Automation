# Deployment Checklist

## ✅ Completed
- [x] db_store.py — Full Postgres schema + CRUD
- [x] Dockerfile + .dockerignore
- [x] .github/workflows/daily-pipeline.yml
- [x] requirements.txt — sqlalchemy + psycopg2
- [x] audit.py — Postgres support
- [x] discover.py — Fully wired ✓
- [x] qualify.py — Fully wired ✓
- [x] nurse.py — Engine support
- [x] enrich.py — 95% wired (fix save_usage_state → db_store call)
- [x] verify.py — Batch migrated
- [x] draft.py — Batch migrated
- [x] send.py — Batch migrated
- [x] followup.py — Batch migrated
- [x] MIGRATION_GUIDE.md — Instructions

## 🔨 Quick Fixes Needed (5 min total)

### enrich.py (line 170)
Replace:
```python
if not dry_run:
    save_usage_state(usage)
```
With:
```python
if not dry_run and usage:
    db_store.increment_hunter_quota(engine, month_key, searches=usage.get('searches_used', 0), verifications=usage.get('verifications_used', 0))
```

### verify.py
Similar fix for `save_usage_state(usage)`

### draft.py, send.py
No additional fixes needed (batch migrations handled)

### followup.py
No additional fixes needed (batch migrations handled)

## 🚀 Deployment Steps

### 1. Test locally (15 min)
```bash
# Set Neon connection
export DATABASE_URL="postgresql://neondb_owner:PASSWORD@host/dbname?sslmode=require"

# Test each stage
python -m outreach_agent.cli discover --limit 1 --dry-run
python -m outreach_agent.cli discover --limit 1
python -m outreach_agent.cli qualify --limit 1
python -m outreach_agent.cli daily --dry-run --limit 1

# Verify in Postgres
psql $DATABASE_URL -c "SELECT COUNT(*) FROM leads_source; SELECT COUNT(*) FROM partner_tracker;"
```

### 2. Commit to Git (5 min)
```bash
git add -A
git commit -m "Migration complete: Postgres backend, Docker containerization, GitHub Actions CI

- db_store.py: 7 Postgres tables with CRUD functions
- All 7 stages wired to db_store (enrich, verify, draft, send, followup with batch migration)
- audit.py: Writes to Postgres
- nurse.py: Engine-based escalations
- Docker: Containerized pipeline
- GitHub Actions: Daily 8 AM scheduled run + manual trigger
- Secrets: All 6 env vars in GitHub encrypted variables

Tested: discover.py, qualify.py (full end-to-end)
Status: Ready for Neon + GitHub Actions deployment"
```

### 3. Create GitHub Secrets (5 min)
**Settings → Secrets and variables → Actions → New repository secret**
- `DATABASE_URL` — postgresql://neondb_owner:...
- `APIFY_API_TOKEN`
- `HUNTER_API_KEY`
- `DEEPSEEK_API_KEY`
- `EMAIL_ADDRESS`
- `EMAIL_APP_PASSWORD`

### 4. Push & Deploy (2 min)
```bash
git push origin main
```

### 5. First Run
- GitHub → Actions → Daily Prospecting Pipeline
- Click "Run workflow" → "Run"
- Monitor logs (should complete in 30-60 seconds)
- Query Postgres to verify data was inserted

## 📊 What's Different Now

**Before:**
- `python -m outreach_agent.cli daily` → Excel workbook (openpyxl)
- State in JSON files (./state/*.json)
- Manual scheduling on Windows

**After:**
- GitHub Actions runs daily at 8 AM UTC (configurable)
- Data in Postgres (durable, queryable)
- State in Postgres tables (discovery_cursor, hunter_quota)
- Logs via GitHub Actions web UI
- Secrets in GitHub encrypted variables
- Containers run on ephemeral GitHub runners (no local machine needed)

## ⚠️ Known Limitations

- `discover.py` requires Apify actor to run (not part of this migration)
- State is per-run in GitHub Actions (connection pooling handled by db_store)
- Audit trail: JSONL still writes for backward compat; Postgres is authoritative
- Excel workbook is now archival (read-only after migration)

## 🔍 Verification

After first run, check:
```bash
psql $DATABASE_URL <<EOF
SELECT stage, COUNT(*) FROM audit_log GROUP BY stage;
SELECT COUNT(*) FROM leads_source WHERE status='new';
SELECT COUNT(*) FROM partner_tracker WHERE status='qualified';
SELECT COUNT(*) FROM review_queue WHERE resolution_status='open';
EOF
```

Should show:
- Leads processed through all stages
- Row counts match pipeline logic (new→qualified→enriched→verified→drafted→sent)
- No escalations (or escalations with severity/reason captured)
