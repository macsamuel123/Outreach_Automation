import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from outreach_agent import audit, config, constants, db_store, eval_layer, nurse
from outreach_agent.clients.deepseek import DeepSeekClient
from outreach_agent.clients.http_base import NonRetriableAPIError, RetriableAPIError


@dataclass
class QualifyResult:
    processed: int
    qualified: int
    rejected: int
    errors: int
    escalated: int
    run_id: str


QUALIFY_SYSTEM_PROMPT = """You are an expert at identifying B2B implementation partners.
Your job is to evaluate companies and decide if they are a good fit for Curate Analytics' partnership program.

A good partner is a firm that:
- Specializes in MIS/ERP implementations (NOT just MSP/managed services)
- Works with mid-to-large enterprises
- Has proven expertise in the specified domain

Respond with JSON: {"decision": "qualify" or "reject", "reasoning": "..."}"""


def run_qualify(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> QualifyResult:
    """Qualify stage: evaluate new leads against criteria and LLM."""

    run_id = run_id or audit.new_run_id()
    engine = db_store.get_engine()
    if not dry_run:
        db_store.ensure_db(engine)

    # Read leads with status=new
    rows = db_store.load_leads(engine, status=constants.LEADS_STATUS_NEW)
    targets = rows[:limit] if limit else rows

    exclude_competitors = set(
        x.lower() for x in cfg.get("qualification", {}).get("exclude_competitors", [])
    )
    exclude_type = cfg.get("qualification", {}).get("exclude_type", "MSP")

    client = DeepSeekClient(settings.deepseek_api_key)

    processed = 0
    qualified = 0
    rejected = 0
    errors = 0
    escalated = 0
    cfg_en = cfg.get("eval_nurse", {})

    for row in targets:
        processed += 1
        company_name = row.get("company_name", "").strip()

        # Pre-filter: competitor name match
        if company_name.lower() in exclude_competitors:
            decision, reasoning = "reject", "Competitor name match"
        else:
            # LLM evaluation
            try:
                user_prompt = f"""Evaluate this company for partnership:

Company: {company_name}
Website: {row.get("website", "")}
Description: {row.get("description", "")}
Employee Size: {row.get("employee_size", "")}

Exclude: {exclude_type} providers
Decision criteria:
1. Is this a {exclude_type}? (exclude if yes)
2. Does the company specialize in MIS/ERP implementation?
3. Would they be a good partner for Curate Analytics?

Provide your assessment."""

                raw = client.chat(
                    system_prompt=QUALIFY_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    response_format_json=True,
                    temperature=0.3,
                )

                parsed = json.loads(raw)
                raw_decision = parsed.get("decision", "")
                decision = raw_decision.strip().lower()
                reasoning = parsed.get("reasoning", "No reasoning provided")

                eval_result = eval_layer.validate_qualify(
                    decision=decision,
                    reasoning=reasoning,
                    raw_decision=raw_decision,
                    min_reasoning_length=cfg_en.get("qualify_min_reasoning_length", 15),
                )

                if not eval_result.passed:
                    def _self_heal_fn(cand, ev):
                        dec, reas = cand
                        if any(i.startswith("invalid_decision") for i in ev.issues):
                            normalized = raw_decision.strip().lower().rstrip(".")
                            if normalized in ("qualify", "reject"):
                                return (normalized, reas)
                            return None
                        if any(i.startswith("thin_reasoning") for i in ev.issues):
                            corrected_raw = client.chat(
                                system_prompt=f"The decision has already been finalized as '{decision}'; write a fuller ≥3-sentence justification for that decision only.",
                                user_prompt=user_prompt,
                                response_format_json=True,
                                temperature=0.3,
                            )
                            corrected_parsed = json.loads(corrected_raw)
                            return (dec, corrected_parsed.get("reasoning", reas))
                        return None

                    def _retry_fn(attempt):
                        retry_raw = client.chat(
                            system_prompt=QUALIFY_SYSTEM_PROMPT,
                            user_prompt=user_prompt,
                            response_format_json=True,
                            temperature=0.3,
                        )
                        retry_parsed = json.loads(retry_raw)
                        retry_dec = retry_parsed.get("decision", "").strip().lower()
                        retry_reas = retry_parsed.get("reasoning", "No reasoning provided")
                        return (retry_dec, retry_reas)

                    def _validate_fn(cand):
                        dec, reas = cand
                        return eval_layer.validate_qualify(
                            decision=dec,
                            reasoning=reas,
                            raw_decision=dec,
                            min_reasoning_length=cfg_en.get("qualify_min_reasoning_length", 15),
                        )

                    try:
                        outcome = nurse.handle(
                            candidate=(decision, reasoning),
                            eval_result=eval_result,
                            validate_fn=_validate_fn,
                            self_heal_fn=_self_heal_fn,
                            retry_fn=_retry_fn,
                            max_retries=cfg_en.get("qualify_max_retries", 1),
                            stage="qualify",
                            run_id=run_id,
                            engine=engine if not dry_run else None,
                            company_name=company_name,
                            website=row.get("website", ""),
                            email=None,
                            source_sheet=constants.SHEET_LEADS_SOURCE,
                            row_ref=row["_row_num"],
                        )
                    except (RetriableAPIError, NonRetriableAPIError, json.JSONDecodeError, KeyError) as e:
                        audit.log_decision(
                            stage="qualify",
                            company_name=company_name,
                            website=row.get("website", ""),
                            email=None,
                            decision="error",
                            reasoning=f"Corrective retry failed: {e}",
                            run_id=run_id,
                            engine=engine if not dry_run else None,
                        )
                        errors += 1
                        continue

                    if outcome.final_status == "escalated":
                        if not dry_run:
                            db_store.update_lead(
                                engine,
                                row["_row_num"],
                                {"status": constants.LEADS_STATUS_NEEDS_REVIEW},
                            )
                        escalated += 1
                        continue
                    decision, reasoning = outcome.final_candidate

            except (RetriableAPIError, NonRetriableAPIError) as e:
                audit.log_decision(
                    stage="qualify",
                    company_name=company_name,
                    website=row.get("website", ""),
                    email=None,
                    decision="error",
                    reasoning=f"API error: {e}",
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                )
                errors += 1
                continue
            except (json.JSONDecodeError, KeyError) as e:
                audit.log_decision(
                    stage="qualify",
                    company_name=company_name,
                    website=row.get("website", ""),
                    email=None,
                    decision="error",
                    reasoning=f"LLM response parse error: {e}",
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                )
                errors += 1
                continue

        # Update Leads_Source status
        if not dry_run:
            db_store.update_lead(
                engine,
                row["_row_num"],
                {
                    "status": (
                        constants.LEADS_STATUS_QUALIFIED
                        if decision == "qualify"
                        else constants.LEADS_STATUS_REJECTED
                    )
                },
            )

        # Log decision
        audit.log_decision(
            stage="qualify",
            company_name=company_name,
            website=row.get("website", ""),
            email=None,
            decision=decision,
            reasoning=reasoning,
            run_id=run_id,
            engine=engine if not dry_run else None,
        )

        # If qualified, append to Partner_Tracker
        if decision == "qualify":
            if not dry_run:
                db_store.append_partner(
                    engine,
                    {
                        "company_name": row.get("company_name"),
                        "website": row.get("website"),
                        "phone": row.get("phone"),
                        "address": row.get("address"),
                        "employee_size": row.get("employee_size"),
                        "description": row.get("description"),
                        "date_added": row.get("date_added"),
                        "source": row.get("source"),
                        "qualify_reasoning": reasoning,
                        "status": constants.PARTNER_STATUS_QUALIFIED,
                    },
                )
            qualified += 1
        else:
            rejected += 1

    return QualifyResult(
        processed=processed,
        qualified=qualified,
        rejected=rejected,
        errors=errors,
        escalated=escalated,
        run_id=run_id,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Qualify stage")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to workbook")
    parser.add_argument("--limit", type=int, help="Limit rows processed")
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_qualify(cfg, settings, dry_run=args.dry_run, limit=args.limit)

    print(
        f"[qualify] Processed: {result.processed}, Qualified: {result.qualified}, "
        f"Rejected: {result.rejected}, Errors: {result.errors} | run_id: {result.run_id}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
