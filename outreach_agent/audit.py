import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import constants

try:
    from . import db_store
except ImportError:
    db_store = None


def new_run_id() -> str:
    """Generate a unique run ID for correlating all operations in one invocation."""
    return uuid.uuid4().hex[:12]


def log_decision(
    *,
    stage: str,
    company_name: str,
    website: str,
    email: str | None,
    decision: str,
    reasoning: str,
    run_id: str,
    jsonl_path: Path = constants.AUDIT_LOG_JSONL_PATH,
    wb=None,
    engine=None,
) -> None:
    """Log a decision to JSONL, Excel (if wb), and/or Postgres (if engine).

    JSONL is written first and must always succeed; Excel/DB writes are best-effort.
    """
    timestamp = datetime.utcnow().isoformat() + "Z"

    log_entry = {
        "timestamp": timestamp,
        "stage": stage,
        "company_name": company_name,
        "website": website,
        "email": email,
        "decision": decision,
        "reasoning": reasoning,
        "run_id": run_id,
    }

    # Write to JSONL (must not fail even if Excel/DB fails)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        raise RuntimeError(f"Failed to write audit log: {e}")

    # Write to Postgres if engine is provided
    if engine and db_store:
        try:
            db_store.append_audit(engine, log_entry)
        except Exception:
            # DB write is best-effort; don't fail the audit if it breaks
            pass

    # Mirror to Excel Audit_Log sheet if workbook is provided (legacy)
    if wb:
        try:
            from . import excel_store
            ws = wb[constants.SHEET_AUDIT_LOG]
            excel_store.append_row(
                ws,
                constants.AUDIT_LOG_COLUMNS,
                log_entry,
            )
        except Exception:
            # Excel mirror is best-effort; don't fail the whole audit if it breaks
            pass
