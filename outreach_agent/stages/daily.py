import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from outreach_agent import audit, config, constants, excel_store, nurse
from outreach_agent.stages import discover, qualify, enrich, verify, draft, send, followup
from outreach_agent.stages.discover import DiscoverResult
from outreach_agent.stages.qualify import QualifyResult
from outreach_agent.stages.enrich import EnrichResult
from outreach_agent.stages.verify import VerifyResult
from outreach_agent.stages.draft import DraftResult
from outreach_agent.stages.send import SendResult
from outreach_agent.stages.followup import FollowupResult


@dataclass
class DailyResult:
    run_id: str
    discover_result: DiscoverResult | None = None
    qualify_result: QualifyResult | None = None
    enrich_result: EnrichResult | None = None
    verify_result: VerifyResult | None = None
    draft_result: DraftResult | None = None
    send_result: SendResult | None = None
    followup_result: FollowupResult | None = None
    stages_completed: int = 0
    stages_failed: list[str] = field(default_factory=list)
    quota_halted_stages: list[str] = field(default_factory=list)


def run_daily(
    cfg: dict,
    settings: config.Settings,
    run_id: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    approve_all_pending: bool = False,
) -> DailyResult:
    """Daily stage: chain discover -> qualify -> enrich -> verify -> draft -> send -> followup
    under one shared run_id.

    Stages run unconditionally in sequence. If a stage raises an exception, it is
    recorded in stages_failed and the chain continues to the next stage regardless
    -- each stage's idempotency model (filtering rows by input status) makes this
    safe, since a downstream stage simply sees fewer eligible rows if an upstream
    stage produced less than expected.

    Unlike other stages, run_daily() prints progress per-substage as it runs
    (rather than leaving printing to the caller), since it is an orchestrator
    that can take several minutes end-to-end and operators need real-time feedback.
    """
    run_id = run_id or audit.new_run_id()
    result = DailyResult(run_id=run_id)

    # discover
    try:
        result.discover_result = discover.run_discover(cfg, settings, run_id=run_id, dry_run=dry_run)
        r = result.discover_result
        print(
            f"[discover] Fetched: {r.fetched}, Inserted: {r.inserted}, "
            f"Deduped: {r.deduped_skipped}, Escalated: {r.escalated} | run_id: {run_id}"
        )
        result.stages_completed += 1
    except Exception as e:
        print(f"[discover] Error: {e} | run_id: {run_id}", file=sys.stderr)
        result.stages_failed.append("discover")

    # qualify
    try:
        result.qualify_result = qualify.run_qualify(cfg, settings, run_id=run_id, dry_run=dry_run, limit=limit)
        r = result.qualify_result
        print(
            f"[qualify] Processed: {r.processed}, Qualified: {r.qualified}, "
            f"Rejected: {r.rejected}, Escalated: {r.escalated}, Errors: {r.errors} | run_id: {run_id}"
        )
        result.stages_completed += 1
    except Exception as e:
        print(f"[qualify] Error: {e} | run_id: {run_id}", file=sys.stderr)
        result.stages_failed.append("qualify")

    # enrich
    try:
        result.enrich_result = enrich.run_enrich(cfg, settings, run_id=run_id, dry_run=dry_run, limit=limit)
        r = result.enrich_result
        print(
            f"[enrich] Processed: {r.processed}, Enriched: {r.enriched}, "
            f"No contacts: {r.no_contacts}, Escalated: {r.escalated} | run_id: {run_id}"
        )
        result.stages_completed += 1
        if r.quota_halted:
            result.quota_halted_stages.append("enrich")
    except Exception as e:
        print(f"[enrich] Error: {e} | run_id: {run_id}", file=sys.stderr)
        result.stages_failed.append("enrich")

    # verify
    try:
        result.verify_result = verify.run_verify(cfg, settings, run_id=run_id, dry_run=dry_run, limit=limit)
        r = result.verify_result
        print(
            f"[verify] Processed: {r.processed}, Verified: {r.verified}, "
            f"Invalid: {r.invalid}, Escalated: {r.escalated} | run_id: {run_id}"
        )
        result.stages_completed += 1
        if r.quota_halted:
            result.quota_halted_stages.append("verify")
    except Exception as e:
        print(f"[verify] Error: {e} | run_id: {run_id}", file=sys.stderr)
        result.stages_failed.append("verify")

    # draft
    try:
        result.draft_result = draft.run_draft(cfg, settings, run_id=run_id, dry_run=dry_run, limit=limit)
        r = result.draft_result
        print(
            f"[draft] Processed: {r.processed}, Drafted: {r.drafted}, "
            f"Escalated: {r.escalated}, Errors: {r.errors} | run_id: {run_id}"
        )
        result.stages_completed += 1
    except Exception as e:
        print(f"[draft] Error: {e} | run_id: {run_id}", file=sys.stderr)
        result.stages_failed.append("draft")

    # send
    try:
        result.send_result = send.run_send(
            cfg, settings, run_id=run_id, dry_run=dry_run, approve_all_pending=approve_all_pending
        )
        r = result.send_result
        print(
            f"[send] Processed: {r.processed}, Sent: {r.sent}, "
            f"Suppressed: {r.suppressed}, Pending: {r.pending_approval}, "
            f"Errors: {r.errors} | run_id: {run_id}"
        )
        result.stages_completed += 1
    except Exception as e:
        print(f"[send] Error: {e} | run_id: {run_id}", file=sys.stderr)
        result.stages_failed.append("send")

    # followup
    try:
        result.followup_result = followup.run_followup(cfg, settings, run_id=run_id, dry_run=dry_run)
        r = result.followup_result
        print(
            f"[followup] FU1 sent: {r.followup1_sent}, FU2 sent: {r.followup2_sent}, "
            f"Pending: {r.pending_approval}, Suppressed: {r.suppressed}, "
            f"Escalated: {r.escalated}, Errors: {r.errors} | run_id: {run_id}"
        )
        result.stages_completed += 1
    except Exception as e:
        print(f"[followup] Error: {e} | run_id: {run_id}", file=sys.stderr)
        result.stages_failed.append("followup")

    # Send digest email if there are escalations
    try:
        wb = excel_store.load()
        review_rows = excel_store.read_rows(wb[constants.SHEET_REVIEW_QUEUE], constants.REVIEW_QUEUE_COLUMNS)
        new_escalations = [r for r in review_rows if r.get("run_id") == run_id]
        if new_escalations and not dry_run:
            nurse.send_digest_email(new_escalations, settings, cfg, run_id=run_id)
    except Exception as e:
        print(f"[daily] Digest email failed (non-fatal): {e}", file=sys.stderr)

    failed_count = len(result.stages_failed)
    quota_count = len(result.quota_halted_stages)
    print(
        f"[daily] Completed {result.stages_completed}/7 stages | "
        f"{quota_count} quota-halted | {failed_count} failed | run_id: {run_id}"
    )
    if result.stages_failed:
        print(f"[daily] Failed stages: {', '.join(result.stages_failed)}")

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Daily stage (full pipeline)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--approve-all-pending", action="store_true")
    args = parser.parse_args(argv)

    cfg = config.load_config(Path(args.config))
    settings = config.load_settings()

    result = run_daily(
        cfg,
        settings,
        dry_run=args.dry_run,
        limit=args.limit,
        approve_all_pending=args.approve_all_pending,
    )

    return 1 if result.stages_failed else 0


if __name__ == "__main__":
    exit(main())
