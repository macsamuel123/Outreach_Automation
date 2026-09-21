import sys
import argparse

from outreach_agent import config, excel_store, constants
from outreach_agent.stages import discover, qualify, enrich, verify, draft, send, followup, optout_poll, daily


def main():
    parser = argparse.ArgumentParser(
        description="Curate Analytics Outreach Automation Pipeline",
        prog="python -m outreach_agent.cli",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available stages")

    # init-workbook
    subparsers.add_parser(
        "init-workbook",
        help="Initialize the workbook (creates all 4 tabs if missing)",
    )

    # discover
    discover_parser = subparsers.add_parser("discover", help="Discover stage")
    discover_parser.add_argument("--config", default="config.yaml")
    discover_parser.add_argument("--dry-run", action="store_true")
    discover_parser.add_argument("--limit", type=int)

    # qualify
    qualify_parser = subparsers.add_parser("qualify", help="Qualify stage")
    qualify_parser.add_argument("--config", default="config.yaml")
    qualify_parser.add_argument("--dry-run", action="store_true")
    qualify_parser.add_argument("--limit", type=int)

    # enrich
    enrich_parser = subparsers.add_parser("enrich", help="Enrich stage")
    enrich_parser.add_argument("--config", default="config.yaml")
    enrich_parser.add_argument("--dry-run", action="store_true")
    enrich_parser.add_argument("--limit", type=int)

    # verify
    verify_parser = subparsers.add_parser("verify", help="Verify stage")
    verify_parser.add_argument("--config", default="config.yaml")
    verify_parser.add_argument("--dry-run", action="store_true")
    verify_parser.add_argument("--limit", type=int)

    # draft
    draft_parser = subparsers.add_parser("draft", help="Draft stage")
    draft_parser.add_argument("--config", default="config.yaml")
    draft_parser.add_argument("--dry-run", action="store_true")
    draft_parser.add_argument("--limit", type=int)

    # send
    send_parser = subparsers.add_parser("send", help="Send stage")
    send_parser.add_argument("--config", default="config.yaml")
    send_parser.add_argument("--dry-run", action="store_true")
    send_parser.add_argument("--approve-all-pending", action="store_true")

    # followup
    followup_parser = subparsers.add_parser("followup", help="Followup stage")
    followup_parser.add_argument("--config", default="config.yaml")
    followup_parser.add_argument("--dry-run", action="store_true")

    # daily
    daily_parser = subparsers.add_parser(
        "daily",
        help="Run the full daily pipeline (discover -> qualify -> enrich -> verify -> draft -> send -> followup)",
    )
    daily_parser.add_argument("--config", default="config.yaml")
    daily_parser.add_argument("--dry-run", action="store_true")
    daily_parser.add_argument("--limit", type=int)
    daily_parser.add_argument("--approve-all-pending", action="store_true")

    # optout-poll
    optout_poll_parser = subparsers.add_parser("optout-poll", help="Opt-out polling stage")
    optout_poll_parser.add_argument("--config", default="config.yaml")
    optout_poll_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Load config early for most commands
    if args.command != "init-workbook":
        try:
            from pathlib import Path
            cfg = config.load_config(Path(args.config if hasattr(args, "config") else "config.yaml"))
            settings = config.load_settings()
        except Exception as e:
            print(f"Config/environment error: {e}", file=sys.stderr)
            return 1

    # Dispatch to stage
    if args.command == "init-workbook":
        excel_store.ensure_workbook(constants.WORKBOOK_PATH)
        print(f"[OK] Workbook initialized at {constants.WORKBOOK_PATH}")
        return 0

    elif args.command == "discover":
        try:
            result = discover.run_discover(cfg, settings, dry_run=args.dry_run)
            print(
                f"[discover] Fetched: {result.fetched}, Inserted: {result.inserted}, "
                f"Deduped: {result.deduped_skipped}, Escalated: {result.escalated} | run_id: {result.run_id}"
            )
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "qualify":
        try:
            result = qualify.run_qualify(cfg, settings, dry_run=args.dry_run, limit=args.limit)
            print(
                f"[qualify] Processed: {result.processed}, Qualified: {result.qualified}, "
                f"Rejected: {result.rejected}, Escalated: {result.escalated}, Errors: {result.errors} | run_id: {result.run_id}"
            )
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "enrich":
        try:
            result = enrich.run_enrich(cfg, settings, dry_run=args.dry_run, limit=args.limit)
            print(
                f"[enrich] Processed: {result.processed}, Enriched: {result.enriched}, "
                f"No contacts: {result.no_contacts}, Escalated: {result.escalated} | run_id: {result.run_id}"
            )
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "verify":
        try:
            result = verify.run_verify(cfg, settings, dry_run=args.dry_run, limit=args.limit)
            print(
                f"[verify] Processed: {result.processed}, Verified: {result.verified}, "
                f"Invalid: {result.invalid}, Escalated: {result.escalated} | run_id: {result.run_id}"
            )
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "draft":
        try:
            result = draft.run_draft(cfg, settings, dry_run=args.dry_run, limit=args.limit)
            print(
                f"[draft] Processed: {result.processed}, Drafted: {result.drafted}, "
                f"Escalated: {result.escalated}, Errors: {result.errors} | run_id: {result.run_id}"
            )
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "send":
        try:
            result = send.run_send(cfg, settings, dry_run=args.dry_run, approve_all_pending=args.approve_all_pending)
            print(
                f"[send] Processed: {result.processed}, Sent: {result.sent}, "
                f"Suppressed: {result.suppressed}, Pending: {result.pending_approval}, "
                f"Errors: {result.errors} | run_id: {result.run_id}"
            )
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "followup":
        try:
            result = followup.run_followup(cfg, settings, dry_run=args.dry_run)
            print(
                f"[followup] FU1 sent: {result.followup1_sent}, FU2 sent: {result.followup2_sent}, "
                f"Pending: {result.pending_approval}, Suppressed: {result.suppressed}, "
                f"Escalated: {result.escalated}, Errors: {result.errors} | run_id: {result.run_id}"
            )
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "daily":
        try:
            result = daily.run_daily(
                cfg,
                settings,
                dry_run=args.dry_run,
                limit=args.limit,
                approve_all_pending=args.approve_all_pending,
            )
            return 1 if result.stages_failed else 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    elif args.command == "optout-poll":
        try:
            result = optout_poll.run_optout_poll(cfg, settings, dry_run=args.dry_run)
            print(
                f"[optout-poll] Fetched: {result.messages_fetched}, Matched: {result.matched_to_leads}, "
                f"Opted-out: {result.opted_out}, Responded: {result.responded}, "
                f"Invalid: {result.invalid} | run_id: {result.run_id}"
            )
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
