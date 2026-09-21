"""Nurse orchestration: retry, self-heal, escalate, and alert."""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from . import audit, constants, db_store
from .clients.mailer import send_email
from .config import Settings
from .eval_layer import EvalResult


@dataclass
class NurseOutcome:
    final_status: str
    attempts_used: int
    final_candidate: object | None
    final_eval: EvalResult


def handle(
    *,
    candidate: object,
    eval_result: EvalResult,
    validate_fn: Callable,
    stage: str,
    run_id: str,
    engine: Optional[object] = None,
    company_name: str,
    website: str,
    email: str | None,
    source_sheet: str,
    row_ref: object,
    self_heal_fn: Callable | None = None,
    retry_fn: Callable | None = None,
    max_retries: int = 2,
) -> NurseOutcome:
    """Handle a failing eval result: self-heal → retry → escalate.

    Self-heal and retry_fn are optional. If both are None or unhelpful,
    escalates immediately. Never catches exceptions from retry_fn/self_heal_fn —
    those propagate to the caller's try/except block."""

    attempts_used = 0
    current_candidate = candidate
    current_eval = eval_result

    if current_eval.recommended_action == "self_heal" and self_heal_fn is not None:
        healed = self_heal_fn(current_candidate, current_eval)
        if healed is not None:
            new_eval = validate_fn(healed)
            if new_eval.passed:
                return NurseOutcome(
                    final_status="healed",
                    attempts_used=0,
                    final_candidate=healed,
                    final_eval=new_eval,
                )
            current_candidate = healed
            current_eval = new_eval

    if retry_fn is not None and current_eval.recommended_action in ("retry", "self_heal"):
        while attempts_used < max_retries:
            attempts_used += 1
            retried = retry_fn(attempts_used)
            new_eval = validate_fn(retried)
            if new_eval.passed:
                return NurseOutcome(
                    final_status="retried",
                    attempts_used=attempts_used,
                    final_candidate=retried,
                    final_eval=new_eval,
                )
            current_candidate = retried
            current_eval = new_eval

    escalate(
        stage=stage,
        run_id=run_id,
        engine=engine,
        company_name=company_name,
        website=website,
        email=email,
        source_sheet=source_sheet,
        row_ref=row_ref,
        eval_result=current_eval,
    )
    return NurseOutcome(
        final_status="escalated",
        attempts_used=attempts_used,
        final_candidate=None,
        final_eval=current_eval,
    )


def escalate(
    *,
    stage: str,
    run_id: str,
    engine: Optional[object] = None,
    company_name: str,
    website: str,
    email: str | None,
    source_sheet: str,
    row_ref: object,
    eval_result: EvalResult,
) -> None:
    """Escalate a failing validation to the Review_Queue."""
    if not engine:
        return

    issue_summary = "; ".join(eval_result.issues) if eval_result.issues else "Unknown issue"

    row_data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "run_id": run_id,
        "stage": stage,
        "source_sheet": source_sheet,
        "row_ref": str(row_ref),
        "company_name": company_name,
        "website": website,
        "contact_email": email,
        "issue_summary": issue_summary,
        "severity": eval_result.severity,
        "recommended_action": eval_result.recommended_action,
        "resolution_status": "open",
        "resolved_at": None,
        "resolved_by": None,
    }

    db_store.append_review_queue(engine, row_data)


def send_digest_email(
    escalations: list[dict],
    settings: Settings,
    cfg: dict,
    run_id: str,
) -> None:
    """Send a digest email listing all escalations from this run."""
    if not escalations:
        return

    eval_cfg = cfg.get("eval_nurse", {})
    smtp_host = cfg.get("outreach", {}).get("smtp_host", "smtp.titan.email")
    smtp_port = cfg.get("outreach", {}).get("smtp_port", 465)
    prefix = eval_cfg.get("digest_subject_prefix", "[Outreach QA]")
    recipient = eval_cfg.get("alert_recipient") or settings.email_address

    subject = f"{prefix} {len(escalations)} item(s) need review - run {run_id}"

    lines = [
        f"QA Alert: {len(escalations)} item(s) require review",
        "",
    ]
    for esc in escalations:
        lines.append(
            f"- [{esc['stage']}] {esc['company_name']} ({esc['website']}) "
            f"severity={esc['severity']}: {esc['issue_summary']}"
        )
    lines.append("")
    lines.append("Review the Review_Queue tab in the workbook for full details.")

    body = "\n".join(lines)

    send_email(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        sender=settings.email_address,
        password=settings.email_app_password,
        to_addr=recipient,
        subject=subject,
        body=body,
    )
