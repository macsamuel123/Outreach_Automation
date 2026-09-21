import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from outreach_agent import audit, config, constants, excel_store, eval_layer, nurse
from outreach_agent.clients.deepseek import DeepSeekClient
from outreach_agent.clients.http_base import RetriableAPIError
from outreach_agent.clients.mailer import send_email
from outreach_agent.domainutil import normalize_domain


@dataclass
class FollowupResult:
    followup1_sent: int
    followup2_sent: int
    pending_approval: int
    suppressed: int
    errors: int
    escalated: int
    run_id: str


def run_followup(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
) -> FollowupResult:
    """Followup stage: send follow-ups for non-responsive leads."""

    run_id = run_id or audit.new_run_id()
    wb = excel_store.load()
    ws_tracker = wb[constants.SHEET_PARTNER_TRACKER]
    ws_suppression = wb[constants.SHEET_SUPPRESSION_LIST]

    suppression_rows = excel_store.read_rows(ws_suppression, constants.SUPPRESSION_LIST_COLUMNS)
    rows = excel_store.read_rows(engine, constants.PARTNER_TRACKER_COLUMNS)

    require_approval = cfg.get("outreach", {}).get("require_manual_approval", True)
    smtp_host = cfg.get("outreach", {}).get("smtp_host", "smtp.gmail.com")
    smtp_port = cfg.get("outreach", {}).get("smtp_port", 465)
    days_followup1 = cfg.get("follow_up", {}).get("days_before_first_followup", 4)
    days_followup2 = cfg.get("follow_up", {}).get("days_before_second_followup", 8)
    max_followups = cfg.get("follow_up", {}).get("max_follow_ups", 2)

    client = DeepSeekClient(settings.deepseek_api_key)

    followup1_sent = 0
    followup2_sent = 0
    pending_approval = 0
    suppressed = 0
    errors = 0
    escalated = 0
    cfg_en = cfg.get("eval_nurse", {})

    today = date.today()

    # Process rows ready for followup1
    for row in rows:
        if row.get("status") != constants.PARTNER_STATUS_SENT:
            continue

        sent_at_str = row.get("sent_at", "")
        try:
            sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue

        days_since = (today - sent_at).days
        if days_since < days_followup1:
            continue

        email = row.get("contact_email", "")
        domain = normalize_domain(email or row.get("website", ""))

        if excel_store.is_suppressed(email, domain, suppression_rows):
            db_store.update_partner(
                engine,
                row["_row_num"],
                
                {"status": constants.PARTNER_STATUS_OPTED_OUT},
            )
            audit.log_decision(
                stage="followup",
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

        # Draft followup
        try:
            user_prompt = f"""Draft a follow-up email (2nd contact):

Original subject: {row.get("sent_subject", "")}
Contact: {row.get("contact_name", "")}
Company: {row.get("company_name", "")}

This is a gentle follow-up reiterating our partnership interest.
Keep it short and professional. Format as JSON."""

            raw = client.chat(
                system_prompt='Generate a follow-up email. Respond with JSON: {"subject": "Re: ...", "body": "..."}',
                user_prompt=user_prompt,
                response_format_json=True,
                temperature=0.7,
            )
            parsed = json.loads(raw)
            followup_subject = parsed.get("subject", f"Re: {row.get('sent_subject', '')}")
            followup_body = parsed.get("body", "")

        except Exception as e:
            audit.log_decision(
                stage="followup",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=email,
                decision="error",
                reasoning=f"Draft generation failed: {e}",
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            errors += 1
            continue

        eval_result = eval_layer.validate_followup(
            subject=followup_subject,
            body=followup_body,
            min_body_length=cfg_en.get("followup_min_body_length", 100),
            max_body_length=cfg_en.get("followup_max_body_length", 2500),
            placeholder_markers=cfg_en.get("draft_placeholder_markers", []),
        )

        if not eval_result.passed:
            def _self_heal_fn(cand, ev):
                s, b = cand
                if any(i.startswith("subject_missing_re_prefix") for i in ev.issues):
                    return (f"Re: {s}" if not s.lower().startswith("re:") else s, b)
                if any(i.startswith("body_too_long") for i in ev.issues):
                    max_len = cfg_en.get("followup_max_body_length", 2500)
                    cut = b.rfind(".", 0, max_len)
                    return (s, b[:cut + 1] if cut > 0 else b[:max_len])
                if any(i.startswith("placeholder_leftover") for i in ev.issues):
                    corrected_raw = client.chat(
                        system_prompt=f"Rewrite ONLY placeholder text. Company: {row.get('company_name', '')}. Contact: {row.get('contact_name', '')}. Original: {b}",
                        user_prompt=user_prompt,
                        response_format_json=True,
                        temperature=0.3,
                    )
                    corrected_parsed = json.loads(corrected_raw)
                    return (corrected_parsed.get("subject", s).strip(), corrected_parsed.get("body", b).strip())
                return None

            def _retry_fn(attempt):
                retry_raw = client.chat(
                    system_prompt='Generate a follow-up email. Respond with JSON: {"subject": "Re: ...", "body": "..."}',
                    user_prompt=user_prompt,
                    response_format_json=True,
                    temperature=0.7,
                )
                retry_parsed = json.loads(retry_raw)
                return (retry_parsed.get("subject", "").strip(), retry_parsed.get("body", "").strip())

            def _validate_fn(cand):
                s, b = cand
                return eval_layer.validate_followup(
                    subject=s,
                    body=b,
                    min_body_length=cfg_en.get("followup_min_body_length", 100),
                    max_body_length=cfg_en.get("followup_max_body_length", 2500),
                    placeholder_markers=cfg_en.get("draft_placeholder_markers", []),
                )

            try:
                outcome = nurse.handle(
                    candidate=(followup_subject, followup_body),
                    eval_result=eval_result,
                    validate_fn=_validate_fn,
                    self_heal_fn=_self_heal_fn,
                    retry_fn=_retry_fn,
                    max_retries=cfg_en.get("followup_max_retries", 2),
                    stage="followup",
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                    company_name=row.get("company_name", ""),
                    website=row.get("website", ""),
                    email=email,
                    source_sheet=constants.SHEET_PARTNER_TRACKER,
                    row_ref=row["_row_num"],
                )
            except (RetriableAPIError, json.JSONDecodeError, KeyError) as e:
                audit.log_decision(
                    stage="followup",
                    company_name=row.get("company_name", ""),
                    website=row.get("website", ""),
                    email=email,
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
            followup_subject, followup_body = outcome.final_candidate

        if require_approval:
            db_store.update_partner(
                engine,
                row["_row_num"],
                
                {
                    "status": constants.PARTNER_STATUS_PENDING_APPROVAL,
                    "pending_action": constants.PENDING_ACTION_FOLLOWUP1,
                    "draft_subject": followup_subject,
                    "draft_body": followup_body,
                },
            )
            audit.log_decision(
                stage="followup",
                company_name=row.get("company_name", ""),
                website=row.get("website", ""),
                email=email,
                decision="pending_approval",
                reasoning="Followup1 drafted, awaiting manual approval",
                run_id=run_id,
                engine=engine if not dry_run else None,
            )
            pending_approval += 1
        else:
            try:
                send_email(
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    sender=settings.email_address,
                    password=settings.email_app_password,
                    to_addr=email,
                    subject=followup_subject,
                    body=followup_body,
                )

                db_store.update_partner(
                    engine,
                    row["_row_num"],
                    
                    {
                        "status": constants.PARTNER_STATUS_FOLLOWUP1_SENT,
                        "followup_1_sent_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
                audit.log_decision(
                    stage="followup",
                    company_name=row.get("company_name", ""),
                    website=row.get("website", ""),
                    email=email,
                    decision="followup1_sent",
                    reasoning="Followup1 email sent successfully",
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                )
                followup1_sent += 1

            except RetriableAPIError as e:
                audit.log_decision(
                    stage="followup",
                    company_name=row.get("company_name", ""),
                    website=row.get("website", ""),
                    email=email,
                    decision="error",
                    reasoning=f"Send failed: {e}",
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                )
                errors += 1

    # Process rows ready for followup2
    if max_followups >= 2:
        for row in rows:
            if row.get("status") != constants.PARTNER_STATUS_FOLLOWUP1_SENT:
                continue

            sent_at_str = row.get("followup_1_sent_at", "")
            try:
                sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                continue

            days_since = (today - sent_at).days
            days_between = days_followup2 - days_followup1
            if days_since < days_between:
                continue

            email = row.get("contact_email", "")
            domain = normalize_domain(email or row.get("website", ""))

            if excel_store.is_suppressed(email, domain, suppression_rows):
                db_store.update_partner(
                    engine,
                    row["_row_num"],
                    
                    {"status": constants.PARTNER_STATUS_OPTED_OUT},
                )
                audit.log_decision(
                    stage="followup",
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

            try:
                user_prompt = f"""Final follow-up email (3rd contact):

Company: {row.get("company_name", "")}
Contact: {row.get("contact_name", "")}

This is the final outreach before we mark this lead as exhausted.
Format as JSON."""

                raw = client.chat(
                    system_prompt='Generate final follow-up. Respond with JSON: {"subject": "Re: ...", "body": "..."}',
                    user_prompt=user_prompt,
                    response_format_json=True,
                    temperature=0.7,
                )
                parsed = json.loads(raw)
                followup_subject = parsed.get("subject", "Final follow-up")
                followup_body = parsed.get("body", "")

            except Exception as e:
                audit.log_decision(
                    stage="followup",
                    company_name=row.get("company_name", ""),
                    website=row.get("website", ""),
                    email=email,
                    decision="error",
                    reasoning=f"Followup2 draft failed: {e}",
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                )
                errors += 1
                continue

            eval_result = eval_layer.validate_followup(
                subject=followup_subject,
                body=followup_body,
                min_body_length=cfg_en.get("followup_min_body_length", 100),
                max_body_length=cfg_en.get("followup_max_body_length", 2500),
                placeholder_markers=cfg_en.get("draft_placeholder_markers", []),
            )

            if not eval_result.passed:
                def _self_heal_fn(cand, ev):
                    s, b = cand
                    if any(i.startswith("subject_missing_re_prefix") for i in ev.issues):
                        return (f"Re: {s}" if not s.lower().startswith("re:") else s, b)
                    if any(i.startswith("body_too_long") for i in ev.issues):
                        max_len = cfg_en.get("followup_max_body_length", 2500)
                        cut = b.rfind(".", 0, max_len)
                        return (s, b[:cut + 1] if cut > 0 else b[:max_len])
                    if any(i.startswith("placeholder_leftover") for i in ev.issues):
                        corrected_raw = client.chat(
                            system_prompt=f"Rewrite ONLY placeholder text. Company: {row.get('company_name', '')}. Contact: {row.get('contact_name', '')}. Original: {b}",
                            user_prompt=user_prompt,
                            response_format_json=True,
                            temperature=0.3,
                        )
                        corrected_parsed = json.loads(corrected_raw)
                        return (corrected_parsed.get("subject", s).strip(), corrected_parsed.get("body", b).strip())
                    return None

                def _retry_fn(attempt):
                    retry_raw = client.chat(
                        system_prompt='Generate final follow-up. Respond with JSON: {"subject": "Re: ...", "body": "..."}',
                        user_prompt=user_prompt,
                        response_format_json=True,
                        temperature=0.7,
                    )
                    retry_parsed = json.loads(retry_raw)
                    return (retry_parsed.get("subject", "").strip(), retry_parsed.get("body", "").strip())

                def _validate_fn(cand):
                    s, b = cand
                    return eval_layer.validate_followup(
                        subject=s,
                        body=b,
                        min_body_length=cfg_en.get("followup_min_body_length", 100),
                        max_body_length=cfg_en.get("followup_max_body_length", 2500),
                        placeholder_markers=cfg_en.get("draft_placeholder_markers", []),
                    )

                try:
                    outcome = nurse.handle(
                        candidate=(followup_subject, followup_body),
                        eval_result=eval_result,
                        validate_fn=_validate_fn,
                        self_heal_fn=_self_heal_fn,
                        retry_fn=_retry_fn,
                        max_retries=cfg_en.get("followup_max_retries", 2),
                        stage="followup",
                        run_id=run_id,
                        engine=engine if not dry_run else None,
                        company_name=row.get("company_name", ""),
                        website=row.get("website", ""),
                        email=email,
                        source_sheet=constants.SHEET_PARTNER_TRACKER,
                        row_ref=row["_row_num"],
                    )
                except (RetriableAPIError, json.JSONDecodeError, KeyError) as e:
                    audit.log_decision(
                        stage="followup",
                        company_name=row.get("company_name", ""),
                        website=row.get("website", ""),
                        email=email,
                        decision="error",
                        reasoning=f"Followup2 corrective retry failed: {e}",
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
                followup_subject, followup_body = outcome.final_candidate

            if require_approval:
                db_store.update_partner(
                    engine,
                    row["_row_num"],
                    
                    {
                        "status": constants.PARTNER_STATUS_PENDING_APPROVAL,
                        "pending_action": constants.PENDING_ACTION_FOLLOWUP2,
                        "draft_subject": followup_subject,
                        "draft_body": followup_body,
                    },
                )
                audit.log_decision(
                    stage="followup",
                    company_name=row.get("company_name", ""),
                    website=row.get("website", ""),
                    email=email,
                    decision="pending_approval",
                    reasoning="Followup2 drafted, awaiting manual approval",
                    run_id=run_id,
                    engine=engine if not dry_run else None,
                )
                pending_approval += 1
            else:
                try:
                    send_email(
                        smtp_host=smtp_host,
                        smtp_port=smtp_port,
                        sender=settings.email_address,
                        password=settings.email_app_password,
                        to_addr=email,
                        subject=followup_subject,
                        body=followup_body,
                    )

                    db_store.update_partner(
                        engine,
                        row["_row_num"],
                        
                        {
                            "status": constants.PARTNER_STATUS_EXHAUSTED,
                            "followup_2_sent_at": datetime.utcnow().isoformat() + "Z",
                        },
                    )
                    audit.log_decision(
                        stage="followup",
                        company_name=row.get("company_name", ""),
                        website=row.get("website", ""),
                        email=email,
                        decision="followup2_sent",
                        reasoning="Followup2 email sent, lead marked exhausted",
                        run_id=run_id,
                        engine=engine if not dry_run else None,
                    )
                    followup2_sent += 1

                except RetriableAPIError as e:
                    audit.log_decision(
                        stage="followup",
                        company_name=row.get("company_name", ""),
                        website=row.get("website", ""),
                        email=email,
                        decision="error",
                        reasoning=f"Followup2 send failed: {e}",
                        run_id=run_id,
                        engine=engine if not dry_run else None,
                    )
                    errors += 1

    return FollowupResult(
        followup1_sent=followup1_sent,
        followup2_sent=followup2_sent,
        pending_approval=pending_approval,
        suppressed=suppressed,
        errors=errors,
        escalated=escalated,
        run_id=run_id,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Followup stage")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_followup(cfg, settings, dry_run=args.dry_run)

    print(
        f"[followup] FU1 sent: {result.followup1_sent}, FU2 sent: {result.followup2_sent}, "
        f"Pending approval: {result.pending_approval}, Suppressed: {result.suppressed}, "
        f"Errors: {result.errors} | run_id: {result.run_id}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
