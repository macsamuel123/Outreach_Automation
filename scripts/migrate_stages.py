#!/usr/bin/env python3
"""Auto-migrate remaining stage files from excel_store to db_store."""

import re
import sys
from pathlib import Path

STAGES = ["enrich", "verify", "draft", "send", "followup"]
REPO_ROOT = Path(__file__).parent.parent
STAGES_DIR = REPO_ROOT / "outreach_agent" / "stages"

REPLACEMENTS = [
    # Imports
    (r"from outreach_agent import ([^;\n]*?), excel_store, ",
     r"from outreach_agent import \1, db_store, "),
    (r"from outreach_agent.clients.hunter import ([^;\n]*?), load_usage_state, save_usage_state",
     r"from outreach_agent.clients.hunter import \1"),

    # Load/ensure DB
    (r"wb = excel_store\.load\(\)",
     r"engine = db_store.get_engine()\n    if not dry_run:\n        db_store.ensure_db(engine)"),
    (r"ws_(?:leads|tracker|review) = wb\[constants\.SHEET_[A-Z_]+\]",
     r""),  # Remove workbook sheet references

    # Read rows
    (r"rows = excel_store\.read_rows\(ws_(?:leads|tracker|review), constants\.(\w+_COLUMNS)\)",
     r"rows = db_store.load_\1.lower().replace('_columns', '').lower()(engine, status='*')"),
    (r"targets = \[r for r in rows if r\.get\(\"status\"\) == constants\.(\w+)\]\[:limit\]",
     r"targets = db_store.load_\1_lower()(engine, status=constants.\1)[:limit]"),

    # Update rows
    (r"excel_store\.update_cells\(\s*ws_(?:leads|tracker),\s*row\[\"_row_num\"\],\s*constants\.(\w+_COLUMNS),\s*(\{[^}]+\})\s*\)",
     r"if not dry_run:\n                db_store.update_partner(engine, row['_row_num'], \2)"),

    # Append rows
    (r"excel_store\.append_row\(\s*ws_(?:leads|tracker|review),\s*constants\.(\w+_COLUMNS),\s*(\{[^}]+\})\s*\)",
     r"if not dry_run:\n                db_store.append_partner(engine, \2)"),

    # Save (remove)
    (r"(if not dry_run:|)\s*excel_store\.save\(wb\)",
     r""),

    # Audit calls - replace wb= with engine=
    (r"wb=wb,",
     r"engine=engine if not dry_run else None,"),

    # Hunter quota
    (r"usage = load_usage_state\([^)]*\)",
     r"month_key = audit.new_run_id()[:7]  # YYYY-MM\n    usage = db_store.get_hunter_quota(engine, month_key)"),
    (r"save_usage_state\(usage\)",
     r"db_store.increment_hunter_quota(engine, month_key, searches=usage.get('searches_used', 0), verifications=usage.get('verifications_used', 0))"),
]

def migrate_stage(stage_name: str):
    """Migrate a single stage file."""
    file_path = STAGES_DIR / f"{stage_name}.py"
    if not file_path.exists():
        print(f"[SKIP] {stage_name}.py not found")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    original = content

    # Simple replacements (handles most cases)
    content = content.replace("from outreach_agent import audit, config, constants, excel_store,",
                             "from outreach_agent import audit, config, constants, db_store,")
    content = content.replace("excel_store.load()", "db_store.get_engine()")
    content = content.replace("excel_store.read_rows(", "db_store.load_partners(")
    content = content.replace("excel_store.append_row(", "db_store.append_partner(")
    content = content.replace("excel_store.update_cells(", "db_store.update_partner(")
    content = content.replace("wb=wb,", "engine=engine if not dry_run else None,")
    content = content.replace("load_usage_state(", "db_store.get_hunter_quota(engine, '2026-09')  # TODO: update month")
    content = content.replace("save_usage_state(", "# TODO: update hunter quota in db_store")

    if content != original:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[OK] Migrated {stage_name}.py")
    else:
        print(f"[SKIP] {stage_name}.py already migrated or no changes")

if __name__ == "__main__":
    print("Migrating remaining stages from excel_store to db_store...")
    for stage in STAGES:
        migrate_stage(stage)
    print("Done! Review changes and update any TODOs manually.")
