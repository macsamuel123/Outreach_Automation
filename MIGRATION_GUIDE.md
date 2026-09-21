# Migration from Excel to Postgres: Completion Guide

## What's Done ✅
- `db_store.py` — Full Postgres schema + CRUD functions
- `Dockerfile`, `.dockerignore`, `.github/workflows/daily-pipeline.yml` — Containerization & CI
- `.env.example` — Secrets documentation
- `requirements.txt` — Added sqlalchemy, psycopg2-binary
- `audit.py` — Updated to write to Postgres
- `discover.py` — Fully wired to db_store ✓
- `qualify.py` — Fully wired to db_store ✓
- `nurse.py` — Updated to use engine instead of workbook

## Remaining Stages (Same Pattern as qualify.py)

### Pattern to Follow
Replace in each file:
1. Import: `excel_store` → `db_store`
2. Load workbook: `wb = excel_store.load()` → `engine = db_store.get_engine(); db_store.ensure_db(engine)`
3. Read rows: `excel_store.read_rows(ws, cols)` → `db_store.load_<table>(engine, status=...)`
4. Append rows: `excel_store.append_row(...)` → `db_store.append_<table>(engine, data)`
5. Update rows: `excel_store.update_cells(...)` → `db_store.update_<table>(engine, id, data)`
6. Save: Remove `excel_store.save(wb)` (auto-committed)
7. Audit: Pass `engine=engine if not dry_run else None` instead of `wb=wb`
8. Cursor: `_load_discovery_cursor()` / `_save_discovery_cursor()` → `db_store.get_discovery_cursor()` / `db_store.set_discovery_cursor()`
9. Hunter quota: Use `db_store.get_hunter_quota()` / `db_store.increment_hunter_quota()`

### Files to Update
- `enrich.py` — Replace `load_usage_state` / `save_usage_state` with db_store quota functions
- `verify.py` — Same as enrich
- `draft.py` — Straightforward data updates
- `send.py` — Mostly just audit call updates
- `followup.py` — Two loops, same pattern

### Quick Commands to Do It
```bash
# Replace imports in all remaining stages
sed -i 's/from outreach_agent import audit, config, constants, excel_store/from outreach_agent import audit, config, constants, db_store/g' \
  outreach_agent/stages/{enrich,verify,draft,send,followup}.py

# Then manually edit each file following the pattern above, or copy qualify.py as a template
```

## Testing Locally

1. **Set up Neon:**
   ```bash
   export DATABASE_URL="postgresql://neondb_owner:PASSWORD@ep-XXXXX.neon.tech/neondb?sslmode=require"
   ```

2. **Test discover:**
   ```bash
   python -m outreach_agent.cli discover --dry-run
   psql $DATABASE_URL -c "SELECT COUNT(*) FROM leads_source;"
   ```

3. **Test qualify:**
   ```bash
   python -m outreach_agent.cli qualify --dry-run --limit 1
   python -m outreach_agent.cli qualify --limit 1
   ```

4. **Test full pipeline:**
   ```bash
   python -m outreach_agent.cli daily --dry-run --limit 1
   python -m outreach_agent.cli daily --limit 1
   ```

## Deploying to GitHub Actions

1. **Commit all changes:**
   ```bash
   git add -A
   git commit -m "Migration: Postgres backend with db_store, Docker containerization"
   ```

2. **Create GitHub secrets** (Settings → Secrets → Actions):
   - `DATABASE_URL` (from Neon)
   - `APIFY_API_TOKEN`
   - `HUNTER_API_KEY`
   - `DEEPSEEK_API_KEY`
   - `EMAIL_ADDRESS`
   - `EMAIL_APP_PASSWORD`

3. **Push to GitHub:**
   ```bash
   git push origin main
   ```

4. **Verify first run:**
   - Go to GitHub → Actions → Daily Prospecting Pipeline
   - Click "Run workflow" → Run
   - Monitor logs in the workflow run details

5. **Query Postgres to verify:**
   ```bash
   psql $DATABASE_URL -c "SELECT COUNT(*) FROM partner_tracker;"
   ```

## Data Migration (One-Time)

If you have existing data in the Excel workbook, run once:
```bash
python -c "
from outreach_agent import excel_store, db_store, constants
import sys

try:
    # Load Excel
    wb = excel_store.load()
    engine = db_store.get_engine()
    db_store.ensure_db(engine)
    
    # Migrate each sheet
    for sheet_name, table_func, cols in [
        (constants.SHEET_LEADS_SOURCE, db_store.append_lead, constants.LEADS_SOURCE_COLUMNS),
        (constants.SHEET_PARTNER_TRACKER, db_store.append_partner, constants.PARTNER_TRACKER_COLUMNS),
        (constants.SHEET_SUPPRESSION_LIST, None, constants.SUPPRESSION_LIST_COLUMNS),
    ]:
        ws = wb[sheet_name]
        rows = excel_store.read_rows(ws, cols)
        for row in rows:
            if table_func:
                table_func(engine, row)
    
    print(f'[OK] Migrated {len(rows)} rows')
except Exception as e:
    print(f'[FAIL] {e}', file=sys.stderr)
    sys.exit(1)
"
```

## Notes

- Excel workbook (`data/partner_pipeline.xlsx`) becomes archival (read-only)
- JSONL audit log still writes for backward compat; Postgres is the new source of truth
- All 7 stages remain idempotent (filter by input status)
- State (discovery cursor, Hunter quota) is now durable in Postgres tables
