from pathlib import Path

WORKBOOK_PATH = Path("data/partner_pipeline.xlsx")
AUDIT_LOG_JSONL_PATH = Path("data/audit_log.jsonl")
STATE_DIR = Path("state")

SHEET_LEADS_SOURCE = "Leads_Source"
SHEET_PARTNER_TRACKER = "Partner_Tracker"
SHEET_SUPPRESSION_LIST = "Suppression_List"
SHEET_AUDIT_LOG = "Audit_Log"
SHEET_REVIEW_QUEUE = "Review_Queue"

LEADS_SOURCE_COLUMNS = [
    "company_name",
    "website",
    "phone",
    "address",
    "employee_size",
    "description",
    "date_added",
    "source",
    "status",
]

PARTNER_TRACKER_COLUMNS = [
    "company_name",
    "website",
    "phone",
    "address",
    "employee_size",
    "description",
    "date_added",
    "source",
    "qualify_reasoning",
    "contact_name",
    "contact_title",
    "contact_email",
    "email_confidence",
    "verification_result",
    "draft_subject",
    "draft_body",
    "status",
    "pending_action",
    "sent_at",
    "sent_subject",
    "sent_recipient",
    "followup_1_sent_at",
    "followup_2_sent_at",
    "last_inbound_at",
    "last_inbound_classification",
    "responded_at",
    "opt_out_at",
    "invalid_at",
    "review_notes",
]

SUPPRESSION_LIST_COLUMNS = ["email", "domain", "date", "reason"]

AUDIT_LOG_COLUMNS = [
    "timestamp",
    "stage",
    "company_name",
    "website",
    "email",
    "decision",
    "reasoning",
    "run_id",
]

REVIEW_QUEUE_COLUMNS = [
    "timestamp",
    "run_id",
    "stage",
    "source_sheet",
    "row_ref",
    "company_name",
    "website",
    "contact_email",
    "issue_summary",
    "severity",
    "recommended_action",
    "resolution_status",
    "resolved_at",
    "resolved_by",
]

# Status vocabulary for Leads_Source.status
LEADS_STATUS_NEW = "new"
LEADS_STATUS_QUALIFIED = "qualified"
LEADS_STATUS_REJECTED = "rejected"
LEADS_STATUS_NEEDS_REVIEW = "needs_review"

# Status vocabulary for Partner_Tracker.status
PARTNER_STATUS_QUALIFIED = "qualified"
PARTNER_STATUS_ENRICHED = "enriched"
PARTNER_STATUS_VERIFIED = "verified"
PARTNER_STATUS_DRAFTED = "drafted"
PARTNER_STATUS_PENDING_APPROVAL = "pending_approval"
PARTNER_STATUS_APPROVED = "approved"
PARTNER_STATUS_SENT = "sent"
PARTNER_STATUS_AWAITING_FOLLOWUP1 = "awaiting_followup1"
PARTNER_STATUS_FOLLOWUP1_SENT = "followup1_sent"
PARTNER_STATUS_AWAITING_FOLLOWUP2 = "awaiting_followup2"
PARTNER_STATUS_FOLLOWUP2_SENT = "followup2_sent"
PARTNER_STATUS_EXHAUSTED = "exhausted"
PARTNER_STATUS_NO_CONTACT_FOUND = "no_contact_found"
PARTNER_STATUS_EMAIL_INVALID = "email_invalid"
PARTNER_STATUS_OPTED_OUT = "opted_out"
PARTNER_STATUS_RESPONDED = "responded"
PARTNER_STATUS_INVALID = "invalid"
PARTNER_STATUS_NEEDS_REVIEW = "needs_review"

# Pending action values
PENDING_ACTION_INITIAL = "initial"
PENDING_ACTION_FOLLOWUP1 = "followup1"
PENDING_ACTION_FOLLOWUP2 = "followup2"
