import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from outreach_agent import audit, config, constants, db_store
from outreach_agent.clients.http_base import RetriableAPIError
from outreach_agent.clients.mailer import send_email
from outreach_agent.domainutil import normalize_domain


@dataclass
class SendResult:
    processed: int
    sent: int
    suppressed: int
    pending_approval: int
    errors: int
    run_id: str


def run_send(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
    approve_all_pending: bool = False,
) -> SendResult:
    """Send stage: deliver emails with manual approval gate."""

    run_id = run_id or audit.new_run_id()
    engine = db_store.get_engine()
    if not dry_run:
        db_store.ensure_db(engine)

    # Read suppression list
    suppression_rows = db_store.load_suppression_list(engine)

    rows = db_store.load_partners(engine, status="*")

    require_approval = cfg.get("outreach", {}).get("require_manual_approval", True)
    smtp_host = cfg.get("outreach", {}).get("smtp_host", "smtp.gmail.com")
    smtp_port = cfg.get("outreach", {}).get("smtp_port", 465)

    if require_approval and not approve_all_pending:
        # Only process drafted rows
        targets = [r for r in rows if r.get("status") == constants.PARTNER_STATUS_DRAFTED]
    else:
        # Process drafted or approved
        targets = [r for r in rows if r.get("status") in (
            constants.PARTNER_STATUS_DRAFTED,
            constants.PARTNER_STATUS_APPROVED,
        )]

    processed = 0
    sent = 0
    suppressed = 0
    pending_approval = 0
    errors = 0

    review_rows = []  # For CSV review artifact

    for row in targets:
        processed += 1
        email = row.get("contact_email", "")
        domain = normalize_domain(email or row.get("website", ""))

        # Hard gate: check suppression
        if excel_store.is_suppressed(email, domain, suppression_rows):
            db_store.update_partner(
                engine,
                row["_row_num"],
                
                {"status": constants.PARTNER_STATUS_OPTED_OUT},
            )
            audit.log_decision(
                stage="send",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=email,
                decision="blocked_suppressed",
                reasoning="Email/domain on suppression list",
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            suppressed += 1
            continue

        # Check approval gate
        if require_approval and row.get("status") != constants.PARTNER_STATUS_APPROVED:
            db_store.update_partner(
                engine,
                row["_row_num"],
                
                {
                    "status": constants.PARTNER_STATUS_PENDING_APPROVAL,
                    "pending_action": constants.PENDING_ACTION_INITIAL,
                },
            )
            audit.log_decision(
                stage="send",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=email,
                decision="pending_approval",
                reasoning="Draft ready, awaiting manual approval before send",
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            review_rows.append(row)
            pending_approval += 1
            continue

        # Actually send
        try:
            send_email(
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                sender=settings.email_address,
                password=settings.email_app_password,
                to_addr=email,
                subject=row.get("draft_subject", ""),
                body=row.get("draft_body", ""),
                custom_headers={
                    "X-Curate-Lead-Id": f"row-{row.get('_row_num', 0)}",
                },
            )

            db_store.update_partner(
                engine,
                row["_row_num"],
                
                {
                    "status": constants.PARTNER_STATUS_SENT,
                    "sent_at": datetime.utcnow().isoformat() + "Z",
                    "sent_subject": row.get("draft_subject", ""),
                    "sent_recipient": email,
                },
            )

            audit.log_decision(
                stage="send",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=email,
                decision="sent",
                reasoning=f"Email sent to {email}",
                run_id=run_id,
                engine=engine if not dry_run else None,
            )

            sent += 1

        except RetriableAPIError as e:
            audit.log_decision(
                stage="send",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=email,
                decision="error",
                reasoning=f"SMTP error: {e}",
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            errors += 1
            continue

    # Write review artifact if there are pending approvals
    if review_rows and not dry_run:
        Path("review").mkdir(exist_ok=True)
        review_path = Path("review") / f"review_{run_id}.csv"

        with open(review_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "row_num",
                    "company_name",
                    "contact_name",
                    "contact_email",
                    "draft_subject",
                    "draft_body_preview",
                    "pending_action",
                ],
            )
            writer.writeheader()

            for row in review_rows:
                body_preview = (row.get("draft_body", "")[:200] + "...")
                writer.writerow(
                    {
                        "row_num": row.get("_row_num"),
                        "company_name": row.get("company_name", ""),
                        "contact_name": row.get("contact_name", ""),
                        "contact_email": row.get("contact_email", ""),
                        "draft_subject": row.get("draft_subject", ""),
                        "draft_body_preview": body_preview,
                        "pending_action": constants.PENDING_ACTION_INITIAL,
                    }
                )

        print(
            f"\n[WARNING] {len(review_rows)} emails awaiting approval.\n"
            f"Review: {review_path}\n"
            f"To approve: Edit Partner_Tracker, set status='approved' for desired rows,\n"
            f"then re-run send stage."
        )

    return SendResult(
        processed=processed,
        sent=sent,
        suppressed=suppressed,
        pending_approval=pending_approval,
        errors=errors,
        run_id=run_id,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Send stage")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--approve-all-pending", action="store_true",
                        help="Send all pending_approval rows (use with caution!)")
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_send(cfg, settings, dry_run=args.dry_run, approve_all_pending=args.approve_all_pending)

    print(
        f"[send] Processed: {result.processed}, Sent: {result.sent}, "
        f"Suppressed: {result.suppressed}, Pending approval: {result.pending_approval}, "
        f"Errors: {result.errors} | run_id: {result.run_id}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
