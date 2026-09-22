import argparse
from dataclasses import dataclass
from pathlib import Path

from outreach_agent import audit, config, constants, db_store, eval_layer, nurse
from outreach_agent.clients.hunter import HunterClient, QuotaExceeded
from outreach_agent.domainutil import normalize_domain


@dataclass
class EnrichResult:
    processed: int
    enriched: int
    no_contacts: int
    escalated: int
    quota_halted: bool
    run_id: str


def run_enrich(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> EnrichResult:
    """Enrich stage: fetch decision-maker contacts from Hunter."""

    run_id = run_id or audit.new_run_id()
    engine = db_store.get_engine()
    if not dry_run:
        db_store.ensure_db(engine)

    rows = db_store.load_partners(engine, status=constants.PARTNER_STATUS_QUALIFIED)
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

    decision_maker_titles = cfg.get("enrichment", {}).get("decision_maker_titles", [])

    processed = 0
    enriched = 0
    no_contacts = 0
    escalated = 0
    quota_halted = False
    cfg_en = cfg.get("eval_nurse", {})

    for row in targets:
        processed += 1
        domain = normalize_domain(row.get("website", ""))

        try:
            candidates = client.domain_search(domain, decision_maker_titles)
        except QuotaExceeded as e:
            audit.log_decision(
                stage="enrich",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=None,
                decision="halted_quota",
                reasoning=str(e),
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            quota_halted = True
            break

        if not candidates:
            db_store.update_partner(
                engine,
                row["_row_num"],
                
                {"status": constants.PARTNER_STATUS_NO_CONTACT_FOUND},
            )
            audit.log_decision(
                stage="enrich",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=None,
                decision="no_contact_found",
                reasoning="Hunter domain_search returned zero decision-maker candidates",
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            no_contacts += 1
            continue

        best = candidates[0]
        eval_result = eval_layer.validate_enrich(
            candidates=candidates,
            selected=best,
            company_domain=domain,
            min_confidence=cfg_en.get("enrich_min_confidence", 50),
        )

        if not eval_result.passed:
            def _self_heal_fn(cand, ev):
                if any(i.startswith("not_highest_confidence_selected") for i in ev.issues):
                    return max(candidates, key=lambda c: c.get("confidence", 0))
                return None

            def _validate_fn(cand):
                return eval_layer.validate_enrich(
                    candidates=candidates,
                    selected=cand,
                    company_domain=domain,
                    min_confidence=cfg_en.get("enrich_min_confidence", 50),
                )

            outcome = nurse.handle(
                candidate=best,
                eval_result=eval_result,
                validate_fn=_validate_fn,
                self_heal_fn=_self_heal_fn,
                retry_fn=None,
                max_retries=0,
                stage="enrich",
                run_id=run_id,
                engine=engine if not dry_run else None,
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=best.get("email"),
                source_sheet=constants.SHEET_PARTNER_TRACKER,
                row_ref=row["_row_num"],
            )

            if outcome.final_status == "escalated":
                db_store.update_partner(
                    engine,
                    row["_row_num"],
                    
                    {"status": constants.PARTNER_STATUS_NEEDS_REVIEW},
                )
                escalated += 1
                continue
            best = outcome.final_candidate

        db_store.update_partner(
            engine,
            row["_row_num"],
            
            {
                "contact_name": best.get("name", ""),
                "contact_title": best.get("position", ""),
                "contact_email": best.get("email", ""),
                "email_confidence": best.get("confidence", 0),
                "status": constants.PARTNER_STATUS_ENRICHED,
            },
        )
        audit.log_decision(
            stage="enrich",
            company_name=row.get("company_name", ""),
            website=row.get("website", ""),
            email=best.get("email"),
            decision="enriched",
            reasoning=f"Selected {best.get('name', '')} ({best.get('position', '')}) confidence={best.get('confidence', 0)}",
            run_id=run_id,
            engine=engine if not dry_run else None,
        )
        enriched += 1

    if not dry_run and usage_dict is not None:
        db_store.increment_hunter_quota(engine, month_key, searches=usage_dict.get('searches_used', 0), verifications=usage_dict.get('verifications_used', 0))

    return EnrichResult(
        processed=processed,
        enriched=enriched,
        no_contacts=no_contacts,
        escalated=escalated,
        quota_halted=quota_halted,
        run_id=run_id,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Enrich stage")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_enrich(cfg, settings, dry_run=args.dry_run, limit=args.limit)

    status = "QUOTA_HALTED" if result.quota_halted else "OK"
    print(
        f"[enrich] Processed: {result.processed}, Enriched: {result.enriched}, "
        f"No contacts: {result.no_contacts}, Status: {status} | run_id: {result.run_id}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
