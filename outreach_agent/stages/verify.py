import argparse
from dataclasses import dataclass
from pathlib import Path

from outreach_agent import audit, config, constants, db_store, eval_layer, nurse
from outreach_agent.clients.hunter import HunterClient, QuotaExceeded


@dataclass
class VerifyResult:
    processed: int
    verified: int
    invalid: int
    escalated: int
    quota_halted: bool
    run_id: str


def run_verify(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> VerifyResult:
    """Verify stage: validate emails with Hunter."""

    run_id = run_id or audit.new_run_id()
    engine = db_store.get_engine()
    if not dry_run:
        db_store.ensure_db(engine)

    rows = db_store.load_partners(engine, status=constants.PARTNER_STATUS_ENRICHED)
    targets = rows[:limit] if limit else rows

    month_key = run_id[:7]
    usage_dict = db_store.get_hunter_quota(engine, month_key) if not dry_run else {}

    # Convert dict to object for HunterClient compatibility
    class UsageObj:
        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)

    usage = UsageObj(usage_dict) if usage_dict is not None else UsageObj({'month_key': month_key, 'searches_used': 0, 'verifications_used': 0})
    client = HunterClient(
        settings.hunter_api_key,
        usage,
        cfg.get("hunter_limits", {}).get("max_searches_per_month", 80),
        cfg.get("hunter_limits", {}).get("max_verifications_total", 2000),
    )

    processed = 0
    verified = 0
    invalid = 0
    escalated = 0
    quota_halted = False
    cfg_en = cfg.get("eval_nurse", {})

    for row in targets:
        processed += 1
        email = row.get("contact_email", "")

        try:
            result = client.verify_email(email)
        except QuotaExceeded as e:
            audit.log_decision(
                stage="verify",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=email,
                decision="halted_quota",
                reasoning=str(e),
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            quota_halted = True
            break

        status_value = result.get("status", "unknown")
        eval_result = eval_layer.validate_verify(result)

        if not eval_result.passed:
            max_retries = cfg_en.get("verify_max_retries", 0)

            def _retry_fn(attempt):
                return client.verify_email(email)

            def _validate_fn(res):
                return eval_layer.validate_verify(res)

            try:
                outcome = nurse.handle(
                    candidate=result,
                    eval_result=eval_result,
                    validate_fn=_validate_fn,
                    self_heal_fn=None,
                    retry_fn=(_retry_fn if max_retries > 0 else None),
                    max_retries=max_retries,
                    stage="verify",
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                    company_name=row.get("company_name", ""),
                    website=row.get("website", ""),
                    email=email,
                    source_sheet=constants.SHEET_PARTNER_TRACKER,
                    row_ref=row["_row_num"],
                )
            except QuotaExceeded as e:
                audit.log_decision(
                    stage="verify",
                    company_name=row.get("company_name", ""),
                    website=row.get("website", ""),
                    email=email,
                    decision="halted_quota",
                    reasoning=str(e),
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                )
                quota_halted = True
                break

            if outcome.final_status == "escalated":
                db_store.update_partner(
                    engine,
                    row["_row_num"],
                    
                    {
                        "verification_result": status_value,
                        "status": constants.PARTNER_STATUS_NEEDS_REVIEW,
                    },
                )
                escalated += 1
                continue
            result = outcome.final_candidate
            status_value = result.get("status", "unknown")

        db_store.update_partner(
            engine,
            row["_row_num"],
            
            {
                "verification_result": status_value,
                "status": (
                    constants.PARTNER_STATUS_VERIFIED
                    if status_value == "valid"
                    else constants.PARTNER_STATUS_EMAIL_INVALID
                ),
            },
        )
        audit.log_decision(
            stage="verify",
            company_name=row.get("company_name", ""),
            website=row.get("website", ""),
            email=email,
            decision=status_value,
            reasoning=f"Hunter verify_email returned status={status_value}, score={result.get('score')}",
            run_id=run_id,
            engine=engine if not dry_run else None,
        )

        if status_value == "valid":
            verified += 1
        else:
            invalid += 1

    if not dry_run and usage_dict is not None:
        db_store.increment_hunter_quota(engine, month_key, searches=usage_dict.get('searches_used', 0), verifications=usage_dict.get('verifications_used', 0))

    return VerifyResult(
        processed=processed,
        verified=verified,
        invalid=invalid,
        escalated=escalated,
        quota_halted=quota_halted,
        run_id=run_id,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify stage")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_verify(cfg, settings, dry_run=args.dry_run, limit=args.limit)

    status = "QUOTA_HALTED" if result.quota_halted else "OK"
    print(
        f"[verify] Processed: {result.processed}, Verified: {result.verified}, "
        f"Invalid: {result.invalid}, Status: {status} | run_id: {result.run_id}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
