import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from outreach_agent import audit, config, constants, excel_store
from outreach_agent.clients.deepseek import DeepSeekClient
from outreach_agent.clients.mailer import poll_inbox
from outreach_agent.domainutil import normalize_domain


@dataclass
class OptoutResult:
    messages_fetched: int
    matched_to_leads: int
    opted_out: int
    responded: int
    invalid: int
    unmatched: int
    run_id: str


def _load_imap_state(path: Path = Path("state/imap_last_uid.json")) -> int:
    """Load last processed IMAP UID."""
    if path.exists():
        with open(path, "r") as f:
            data = json.load(f)
        return data.get("last_uid", 0)
    return 0


def _save_imap_state(uid: int, path: Path = Path("state/imap_last_uid.json")) -> None:
    """Save last processed IMAP UID."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"last_uid": uid}, f)


def run_optout_poll(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
) -> OptoutResult:
    """Opt-out polling stage: check for unsubscribe/reply emails."""

    run_id = run_id or audit.new_run_id()
    wb = excel_store.load()
    ws_tracker = wb[constants.SHEET_PARTNER_TRACKER]
    ws_suppression = wb[constants.SHEET_SUPPRESSION_LIST]

    # Load IMAP state
    last_uid = _load_imap_state()

    # Poll inbox
    imap_host = cfg.get("outreach", {}).get("imap_host", "imap.gmail.com")
    imap_port = cfg.get("outreach", {}).get("imap_port", 993)

    try:
        messages = poll_inbox(
            imap_host=imap_host,
            email_address=settings.email_address,
            password=settings.email_app_password,
        )
    except Exception as e:
        audit.log_decision(
            stage="optout_poll",
            company_name="N/A",
            website="N/A",
            email=None,
            decision="error",
            reasoning=f"IMAP poll failed: {e}",
            run_id=run_id,
            wb=wb,
        )
        excel_store.save(wb) if not dry_run else None
        return OptoutResult(
            messages_fetched=0,
            matched_to_leads=0,
            opted_out=0,
            responded=0,
            invalid=0,
            unmatched=0,
            run_id=run_id,
        )

    # Build email index from Partner_Tracker
    rows = excel_store.read_rows(ws_tracker, constants.PARTNER_TRACKER_COLUMNS)
    by_email = {r.get("contact_email", "").lower(): r for r in rows if r.get("contact_email")}

    messages_fetched = len(messages)
    matched_to_leads = 0
    opted_out = 0
    responded = 0
    invalid = 0
    unmatched = 0

    opt_out_keywords = [kw.lower() for kw in cfg.get("opt_out", {}).get("keyword_triggers", [])]
    client = DeepSeekClient(settings.deepseek_api_key)

    max_uid = last_uid

    for msg in messages:
        max_uid = max(max_uid, msg.uid)

        from_addr = msg.from_addr.lower()
        row = by_email.get(from_addr)

        if not row:
            audit.log_decision(
                stage="optout_poll",
                company_name="N/A",
                website="N/A",
                email=from_addr,
                decision="unmatched_inbound",
                reasoning="Sender not in tracked leads",
                run_id=run_id,
                wb=wb,
            )
            unmatched += 1
            continue

        matched_to_leads += 1

        # Classify reply: keyword match first
        text = f"{msg.subject} {msg.body_text}".lower()
        keyword_hit = any(kw in text for kw in opt_out_keywords)

        if keyword_hit:
            classification = "opt_out"
            reasoning = "Keyword match in email"
        else:
            # LLM fallback
            try:
                raw = client.chat(
                    system_prompt='Classify email reply. Respond with JSON: {"classification": "opt_out|interested|not_interested|bounce|other", "reasoning": "..."}',
                    user_prompt=f"Subject: {msg.subject}\n\nBody: {msg.body_text}",
                    response_format_json=True,
                    temperature=0.3,
                )
                parsed = json.loads(raw)
                classification = parsed.get("classification", "other")
                reasoning = parsed.get("reasoning", "LLM classification")
            except Exception:
                classification = "other"
                reasoning = "LLM classification failed, defaulting to other"

        # Update Partner_Tracker with inbound info
        excel_store.update_cells(
            ws_tracker,
            row["_row_num"],
            constants.PARTNER_TRACKER_COLUMNS,
            {
                "last_inbound_at": msg.date.isoformat() + "Z",
                "last_inbound_classification": classification,
            },
        )

        # Process classification
        if classification == "opt_out":
            # Add to Suppression_List
            email_domain = normalize_domain(from_addr)
            excel_store.append_row(
                ws_suppression,
                constants.SUPPRESSION_LIST_COLUMNS,
                {
                    "email": from_addr,
                    "domain": email_domain,
                    "date": date.today().isoformat(),
                    "reason": "Opt-out reply",
                },
            )

            excel_store.update_cells(
                ws_tracker,
                row["_row_num"],
                constants.PARTNER_TRACKER_COLUMNS,
                {
                    "status": constants.PARTNER_STATUS_OPTED_OUT,
                    "opt_out_at": date.today().isoformat(),
                },
            )
            opted_out += 1

        elif classification == "bounce":
            excel_store.update_cells(
                ws_tracker,
                row["_row_num"],
                constants.PARTNER_TRACKER_COLUMNS,
                {
                    "status": constants.PARTNER_STATUS_INVALID,
                    "invalid_at": date.today().isoformat(),
                },
            )
            invalid += 1

        elif classification in ("interested", "not_interested", "other"):
            excel_store.update_cells(
                ws_tracker,
                row["_row_num"],
                constants.PARTNER_TRACKER_COLUMNS,
                {
                    "status": constants.PARTNER_STATUS_RESPONDED,
                    "responded_at": date.today().isoformat(),
                },
            )
            responded += 1

        audit.log_decision(
            stage="optout_poll",
            company_name=row.get("company_name", ""),
            website=row.get("website", ""),
            email=from_addr,
            decision=classification,
            reasoning=reasoning,
            run_id=run_id,
            wb=wb,
        )

    if not dry_run:
        _save_imap_state(max_uid)
        excel_store.save(wb)

    return OptoutResult(
        messages_fetched=messages_fetched,
        matched_to_leads=matched_to_leads,
        opted_out=opted_out,
        responded=responded,
        invalid=invalid,
        unmatched=unmatched,
        run_id=run_id,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Opt-out polling stage")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_optout_poll(cfg, settings, dry_run=args.dry_run)

    print(
        f"[optout-poll] Fetched: {result.messages_fetched}, Matched: {result.matched_to_leads}, "
        f"Opted-out: {result.opted_out}, Responded: {result.responded}, "
        f"Invalid: {result.invalid}, Unmatched: {result.unmatched} | run_id: {result.run_id}"
    )

    return 0


if __name__ == "__main__":
    exit(main())
