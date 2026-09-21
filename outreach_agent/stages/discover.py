import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from outreach_agent import audit, config, constants, db_store, eval_layer, nurse
from outreach_agent.clients.apify import ApifyClient
from outreach_agent.clients.http_base import NonRetriableAPIError, RetriableAPIError
from outreach_agent.domainutil import normalize_domain


@dataclass
class DiscoverResult:
    fetched: int
    inserted: int
    deduped_skipped: int
    escalated: int
    run_id: str


def run_discover(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
) -> DiscoverResult:
    """Discover stage: fetch companies from Apify, dedupe, and store."""

    run_id = run_id or audit.new_run_id()
    engine = db_store.get_engine()
    db_store.ensure_db(engine)  # Create tables if needed (safe to call multiple times)

    # Build domain index from existing leads
    existing_rows = db_store.load_leads(engine, status="*")  # Load all for dedup check
    existing_domains = set(normalize_domain(row.get("website", "")) for row in existing_rows if row.get("website"))

    # Get daily_target and categories from config
    daily_target = cfg["discovery"].get("daily_target", 100)
    categories = cfg["discovery"].get("categories", [])

    if not categories:
        audit.log_decision(
            stage="discover",
            company_name="N/A",
            website="N/A",
            email=None,
            decision="halted_no_categories",
            reasoning="No categories configured in discovery.categories",
            run_id=run_id,
            engine=engine if not dry_run else None,
        )
        return DiscoverResult(fetched=0, inserted=0, deduped_skipped=0, escalated=0, run_id=run_id)

    # Get actor_id from config
    actor_id = cfg["discovery"].get("actor_id", "")
    if not actor_id:
        audit.log_decision(
            stage="discover",
            company_name="N/A",
            website="N/A",
            email=None,
            decision="halted_no_actor_id",
            reasoning="discovery.actor_id not configured",
            run_id=run_id,
            engine=engine if not dry_run else None,
        )
        return DiscoverResult(fetched=0, inserted=0, deduped_skipped=0, escalated=0, run_id=run_id)

    # Count today's inserts so far
    today = date.today().isoformat()
    today_count = sum(
        1 for row in existing_rows if row.get("date_added") == today
    )
    today_remaining = max(0, daily_target - today_count)

    if today_remaining <= 0:
        audit.log_decision(
            stage="discover",
            company_name="N/A",
            website="N/A",
            email=None,
            decision="daily_target_met",
            reasoning=f"Daily target of {daily_target} already met ({today_count} inserted today)",
            run_id=run_id,
            engine=engine if not dry_run else None,
        )
        return DiscoverResult(fetched=0, inserted=0, deduped_skipped=0, escalated=0, run_id=run_id)

    # Pick category via round-robin cursor
    cursor = db_store.get_discovery_cursor(engine) if not dry_run else 0
    category_url = categories[cursor % len(categories)]
    next_cursor = (cursor + 1) % len(categories)
    if not dry_run:
        db_store.set_discovery_cursor(engine, next_cursor)

    # Fetch from Apify
    client = ApifyClient(settings.apify_api_token)

    try:
        dataset_id = client.run_actor_sync(
            actor_id=actor_id,
            run_input={"category_url": category_url},
            poll_interval_s=5,
            timeout_s=600,
        )
        items = client.get_dataset_items(dataset_id, limit=1000)
    except NonRetriableAPIError as e:
        audit.log_decision(
            stage="discover",
            company_name="N/A",
            website="N/A",
            email=None,
            decision="error",
            reasoning=f"Non-retriable API error: {e}",
            run_id=run_id,
            engine=engine if not dry_run else None,
        )
        return DiscoverResult(fetched=0, inserted=0, deduped_skipped=0, escalated=0, run_id=run_id)
    except RetriableAPIError as e:
        audit.log_decision(
            stage="discover",
            company_name="N/A",
            website="N/A",
            email=None,
            decision="error",
            reasoning=f"API error (retriable): {e}",
            run_id=run_id,
            engine=engine if not dry_run else None,
        )
        return DiscoverResult(fetched=0, inserted=0, deduped_skipped=0, escalated=0, run_id=run_id)

    # Process items: dedupe and insert
    fetched = len(items)
    inserted = 0
    deduped_skipped = 0
    escalated = 0
    cfg_en = cfg.get("eval_nurse", {})

    for item in items:
        if inserted >= today_remaining:
            break

        domain = normalize_domain(item.get("website", ""))
        if not domain or domain in existing_domains:
            deduped_skipped += 1
            continue

        eval_result = eval_layer.validate_discover_item(
            item=item,
            placeholder_values=cfg_en.get("discover_placeholder_values", []),
        )

        if not eval_result.passed:
            def _self_heal_fn(cand, ev):
                if any(i.startswith("placeholder_description") for i in ev.issues):
                    healed = dict(cand)
                    healed["description"] = ""
                    return healed
                return None

            outcome = nurse.handle(
                candidate=item,
                eval_result=eval_result,
                validate_fn=lambda it: eval_layer.validate_discover_item(
                    item=it,
                    placeholder_values=cfg_en.get("discover_placeholder_values", []),
                ),
                self_heal_fn=_self_heal_fn,
                retry_fn=None,
                max_retries=0,
                stage="discover",
                run_id=run_id,
                engine=engine if not dry_run else None,
                company_name=item.get("name", "") or item.get("company_name", ""),
                website=item.get("website", ""),
                email=None,
                source_sheet=constants.SHEET_LEADS_SOURCE,
                row_ref="pre-insert",
            )

            if outcome.final_status == "escalated":
                escalated += 1
                continue
            item = outcome.final_candidate

        # Insert into Leads_Source
        if not dry_run:
            db_store.append_lead(
                engine,
                {
                    "company_name": item.get("name", "") or item.get("company_name", ""),
                    "website": item.get("website", ""),
                    "phone": item.get("phone", ""),
                    "address": item.get("address", ""),
                    "employee_size": item.get("employee_size", ""),
                    "description": item.get("description", ""),
                    "date_added": today,
                    "source": category_url,
                    "status": constants.LEADS_STATUS_NEW,
                },
            )

        existing_domains.add(domain)
        inserted += 1

    audit.log_decision(
        stage="discover",
        company_name=f"batch_summary",
        website="N/A",
        email=None,
        decision="batch_complete",
        reasoning=f"Fetched {fetched}, inserted {inserted}, deduped {deduped_skipped}",
        run_id=run_id,
        engine=engine if not dry_run else None,
    )

    return DiscoverResult(
        fetched=fetched, inserted=inserted, deduped_skipped=deduped_skipped, escalated=escalated, run_id=run_id
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Discover stage")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to workbook")
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_discover(cfg, settings, dry_run=args.dry_run)

    print(
        f"[discover] Fetched: {result.fetched}, Inserted: {result.inserted}, "
        f"Deduped: {result.deduped_skipped}, Escalated: {result.escalated} | run_id: {result.run_id}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
