import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from outreach_agent import audit, config, constants, db_store, eval_layer, nurse
from outreach_agent.clients.deepseek import DeepSeekClient
from outreach_agent.clients.http_base import NonRetriableAPIError, RetriableAPIError


@dataclass
class DraftResult:
    processed: int
    drafted: int
    errors: int
    escalated: int
    run_id: str


DRAFT_SYSTEM_PROMPT = """You are an expert at crafting personalized B2B outreach emails.

Write professional, personalized emails that:
- Reference specific details about the company
- Keep the tone consultative and respectful
- Focus on partnership value
- Include a clear call-to-action

Respond with JSON: {"subject": "...", "body": "..."}"""


def run_draft(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> DraftResult:
    """Draft stage: generate personalized emails."""

    run_id = run_id or audit.new_run_id()
    engine = db_store.get_engine()
    if not dry_run:
        db_store.ensure_db(engine)

    rows = db_store.load_partners(engine, status=constants.PARTNER_STATUS_VERIFIED)
    targets = rows[:limit] if limit else rows

    client = DeepSeekClient(settings.deepseek_api_key)
    require_subject_line = cfg.get("outreach", {}).get("require_subject_line", True)
    sender_line = cfg.get("outreach", {}).get("sender_line", "I lead business development at Curate Analytics")

    processed = 0
    drafted = 0
    errors = 0
    escalated = 0
    cfg_en = cfg.get("eval_nurse", {})

    for row in targets:
        processed += 1
        company_name = row.get("company_name", "")
        contact_name = row.get("contact_name", "")

        try:
            user_prompt = f"""Draft a personalized outreach email:

Company: {company_name}
Contact: {contact_name} ({row.get("contact_title", "")})
Company Description: {row.get("description", "")}

Email context:
- Sender: {sender_line}
- Purpose: Partner with them for MIS/ERP implementations
- Personalization: Reference their company and expertise

Create a professional, engaging email that opens a conversation."""

            raw = client.chat(
                system_prompt=DRAFT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_format_json=True,
                temperature=0.7,
            )

            parsed = json.loads(raw)
            subject = parsed.get("subject", "").strip()
            body = parsed.get("body", "").strip()

            eval_result = eval_layer.validate_draft(
                subject=subject,
                body=body,
                require_subject_line=require_subject_line,
                min_body_length=cfg_en.get("draft_min_body_length", 200),
                max_body_length=cfg_en.get("draft_max_body_length", 3000),
                placeholder_markers=cfg_en.get("draft_placeholder_markers", []),
            )

            if not eval_result.passed:
                def _self_heal_fn(cand, ev):
                    s, b = cand
                    if any(i.startswith("body_too_long") for i in ev.issues):
                        max_len = cfg_en.get("draft_max_body_length", 3000)
                        cut = b.rfind(".", 0, max_len)
                        return (s, b[:cut + 1] if cut > 0 else b[:max_len])
                    if any(i.startswith("placeholder_leftover") for i in ev.issues):
                        corrected_raw = client.chat(
                            system_prompt=f"Rewrite ONLY placeholder text. Company: {company_name}. Contact: {contact_name}. Original: {b}",
                            user_prompt=user_prompt,
                            response_format_json=True,
                            temperature=0.3,
                        )
                        corrected_parsed = json.loads(corrected_raw)
                        return (corrected_parsed.get("subject", s).strip(), corrected_parsed.get("body", b).strip())
                    return None

                def _retry_fn(attempt):
                    retry_raw = client.chat(
                        system_prompt=DRAFT_SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        response_format_json=True,
                        temperature=0.7,
                    )
                    retry_parsed = json.loads(retry_raw)
                    return (retry_parsed.get("subject", "").strip(), retry_parsed.get("body", "").strip())

                def _validate_fn(cand):
                    s, b = cand
                    return eval_layer.validate_draft(
                        subject=s,
                        body=b,
                        require_subject_line=require_subject_line,
                        min_body_length=cfg_en.get("draft_min_body_length", 200),
                        max_body_length=cfg_en.get("draft_max_body_length", 3000),
                        placeholder_markers=cfg_en.get("draft_placeholder_markers", []),
                    )

                try:
                    outcome = nurse.handle(
                        candidate=(subject, body),
                        eval_result=eval_result,
                        validate_fn=_validate_fn,
                        self_heal_fn=_self_heal_fn,
                        retry_fn=_retry_fn,
                        max_retries=cfg_en.get("draft_max_retries", 2),
                        stage="draft",
                        run_id=run_id,
                        engine=engine if not dry_run else None,
                        company_name=company_name,
                        website=row.get("website", ""),
                        email=row.get("contact_email", ""),
                        source_sheet=constants.SHEET_PARTNER_TRACKER,
                        row_ref=row["_row_num"],
                    )
                except (RetriableAPIError, NonRetriableAPIError, json.JSONDecodeError, KeyError) as e:
                    audit.log_decision(
                        stage="draft",
                        company_name=company_name,
                        website=row.get("website", ""),
                        email=row.get("contact_email", ""),
                        decision="error",
                        reasoning=f"Corrective retry failed: {e}",
                        run_id=run_id,
                        engine=engine if not dry_run else None,
                    )
                    errors += 1
                    continue

                if outcome.final_status == "escalated":
                    db_store.update_partner(
                        engine,
                        row["_row_num"],
                        
                        {"status": constants.PARTNER_STATUS_NEEDS_REVIEW},
                    )
                    escalated += 1
                    continue
                subject, body = outcome.final_candidate

            db_store.update_partner(
                engine,
                row["_row_num"],
                
                {
                    "draft_subject": subject,
                    "draft_body": body,
                    "status": constants.PARTNER_STATUS_DRAFTED,
                },
            )
            drafted += 1

        except (RetriableAPIError, NonRetriableAPIError, json.JSONDecodeError, KeyError) as e:
            audit.log_decision(
                stage="draft",
                company_name=company_name,
                website=row.get("website", ""),
                email=row.get("contact_email", ""),
                decision="error",
                reasoning=f"Draft generation failed: {e}",
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            errors += 1
            continue

    return DraftResult(processed=processed, drafted=drafted, errors=errors, escalated=escalated, run_id=run_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Draft stage")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_draft(cfg, settings, dry_run=args.dry_run, limit=args.limit)

    print(
        f"[draft] Processed: {result.processed}, Drafted: {result.drafted}, "
        f"Escalated: {result.escalated}, Errors: {result.errors} | run_id: {result.run_id}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
