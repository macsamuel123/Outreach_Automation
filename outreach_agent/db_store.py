"""Database access layer for Postgres. Replaces openpyxl/excel_store."""

import os
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, Float, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import Engine

Base = declarative_base()


class LeadsSource(Base):
    """Leads_Source sheet schema."""
    __tablename__ = "leads_source"

    id = Column(Integer, primary_key=True)
    company_name = Column(String(500), nullable=False)
    website = Column(String(500))
    phone = Column(String(50))
    address = Column(String(500))
    employee_size = Column(String(100))
    description = Column(Text)
    date_added = Column(String(50))
    source = Column(String(500))
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PartnerTracker(Base):
    """Partner_Tracker sheet schema."""
    __tablename__ = "partner_tracker"

    id = Column(Integer, primary_key=True)
    company_name = Column(String(500), nullable=False)
    website = Column(String(500))
    phone = Column(String(50))
    address = Column(String(500))
    employee_size = Column(String(100))
    description = Column(Text)
    date_added = Column(String(50))
    source = Column(String(500))
    qualify_reasoning = Column(Text)
    contact_name = Column(String(500))
    contact_title = Column(String(500))
    contact_email = Column(String(500))
    email_confidence = Column(Integer)
    verification_result = Column(String(100))
    draft_subject = Column(String(500))
    draft_body = Column(Text)
    status = Column(String(50), nullable=False, index=True)
    pending_action = Column(String(50))
    sent_at = Column(String(50))
    sent_subject = Column(String(500))
    sent_recipient = Column(String(500))
    followup_1_sent_at = Column(String(50))
    followup_2_sent_at = Column(String(50))
    last_inbound_at = Column(String(50))
    last_inbound_classification = Column(String(100))
    responded_at = Column(String(50))
    opt_out_at = Column(String(50))
    invalid_at = Column(String(50))
    review_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SuppressionList(Base):
    """Suppression_List sheet schema."""
    __tablename__ = "suppression_list"

    id = Column(Integer, primary_key=True)
    email = Column(String(500), nullable=False, index=True)
    domain = Column(String(500), nullable=False, index=True)
    date = Column(String(50))
    reason = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """Audit_Log table (replaces JSONL + Excel sheet)."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(String(50), nullable=False)
    stage = Column(String(50), nullable=False, index=True)
    company_name = Column(String(500))
    website = Column(String(500))
    email = Column(String(500))
    decision = Column(String(500))
    reasoning = Column(Text)
    run_id = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReviewQueue(Base):
    """Review_Queue sheet schema."""
    __tablename__ = "review_queue"

    id = Column(Integer, primary_key=True)
    timestamp = Column(String(50), nullable=False)
    run_id = Column(String(50), nullable=False, index=True)
    stage = Column(String(50), nullable=False)
    source_sheet = Column(String(50))
    row_ref = Column(String(100))
    company_name = Column(String(500))
    website = Column(String(500))
    contact_email = Column(String(500))
    issue_summary = Column(Text)
    severity = Column(String(50))
    recommended_action = Column(String(100))
    resolution_status = Column(String(50), default="open")
    resolved_at = Column(String(50))
    resolved_by = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)


class DiscoveryCursor(Base):
    """Replaces state/discovery_cursor.json."""
    __tablename__ = "discovery_cursor"

    id = Column(Integer, primary_key=True)
    category_index = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HunterQuota(Base):
    """Replaces state/hunter_usage.json."""
    __tablename__ = "hunter_quota"

    id = Column(Integer, primary_key=True)
    month_key = Column(String(50), nullable=False, unique=True, index=True)
    searches_used = Column(Integer, default=0)
    verifications_used = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Global engine (created once per process)
_engine: Optional[Engine] = None


def get_db_connection_string() -> str:
    """Get Postgres connection string from DATABASE_URL env var."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable not set. "
            "Set it to: postgresql://user:password@host/dbname?sslmode=require"
        )
    return db_url


def get_engine() -> Engine:
    """Get or create the database engine (connection pool)."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_db_connection_string(),
            pool_pre_ping=True,
            echo=False,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def ensure_db(engine: Engine = None) -> None:
    """Create all tables if they don't exist."""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)


def get_session(engine: Engine = None) -> Session:
    """Get a new database session."""
    if engine is None:
        engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


# === Leads_Source CRUD ===

def load_leads(engine: Engine, status: str) -> list[dict]:
    """Load leads with given status (replaces read_rows(ws_leads, ...))."""
    session = get_session(engine)
    rows = session.query(LeadsSource).filter_by(status=status).all()
    result = [
        {
            **{col.name: getattr(row, col.name) for col in LeadsSource.__table__.columns},
            "_row_num": row.id,  # Preserve Excel-like row reference for idempotency
        }
        for row in rows
    ]
    session.close()
    return result


def append_lead(engine: Engine, values: dict) -> int:
    """Insert a new lead (replaces append_row(ws_leads, ...))."""
    session = get_session(engine)
    lead = LeadsSource(**{k: v for k, v in values.items() if k != "_row_num"})
    session.add(lead)
    session.commit()
    lead_id = lead.id
    session.close()
    return lead_id


def update_lead(engine: Engine, lead_id: int, values: dict) -> None:
    """Update an existing lead."""
    session = get_session(engine)
    session.query(LeadsSource).filter_by(id=lead_id).update(values)
    session.commit()
    session.close()


# === Partner_Tracker CRUD ===

def load_partners(engine: Engine, status: str) -> list[dict]:
    """Load partners with given status."""
    session = get_session(engine)
    rows = session.query(PartnerTracker).filter_by(status=status).all()
    result = [
        {
            **{col.name: getattr(row, col.name) for col in PartnerTracker.__table__.columns},
            "_row_num": row.id,
        }
        for row in rows
    ]
    session.close()
    return result


def append_partner(engine: Engine, values: dict) -> int:
    """Insert a new partner record."""
    session = get_session(engine)
    partner = PartnerTracker(**{k: v for k, v in values.items() if k != "_row_num"})
    session.add(partner)
    session.commit()
    partner_id = partner.id
    session.close()
    return partner_id


def update_partner(engine: Engine, partner_id: int, values: dict) -> None:
    """Update an existing partner."""
    session = get_session(engine)
    session.query(PartnerTracker).filter_by(id=partner_id).update(values)
    session.commit()
    session.close()


# === Suppression_List CRUD ===

def load_suppression_list(engine: Engine) -> list[dict]:
    """Load all suppression entries."""
    session = get_session(engine)
    rows = session.query(SuppressionList).all()
    result = [
        {col.name: getattr(row, col.name) for col in SuppressionList.__table__.columns}
        for row in rows
    ]
    session.close()
    return result


def is_suppressed(email: str, domain: str, suppression_rows: list[dict]) -> bool:
    """Check if an email/domain is in the suppression list."""
    return any(
        (row["email"] and row["email"].lower() == email.lower())
        or (row["domain"] and row["domain"].lower() == domain.lower())
        for row in suppression_rows
    )


# === Audit_Log CRUD ===

def append_audit(engine: Engine, values: dict) -> None:
    """Insert an audit entry (replaces audit.log_decision JSONL write)."""
    session = get_session(engine)
    audit = AuditLog(**values)
    session.add(audit)
    session.commit()
    session.close()


# === Review_Queue CRUD ===

def load_review_queue(engine: Engine, run_id: str = None) -> list[dict]:
    """Load review queue entries, optionally filtered by run_id."""
    session = get_session(engine)
    query = session.query(ReviewQueue)
    if run_id:
        query = query.filter_by(run_id=run_id)
    rows = query.all()
    result = [
        {col.name: getattr(row, col.name) for col in ReviewQueue.__table__.columns}
        for row in rows
    ]
    session.close()
    return result


def append_review_queue(engine: Engine, values: dict) -> None:
    """Insert a review queue entry (escalation)."""
    session = get_session(engine)
    review = ReviewQueue(**values)
    session.add(review)
    session.commit()
    session.close()


# === Discovery_Cursor CRUD ===

def get_discovery_cursor(engine: Engine) -> int:
    """Get the current discovery category index."""
    session = get_session(engine)
    cursor_row = session.query(DiscoveryCursor).first()
    if not cursor_row:
        cursor_row = DiscoveryCursor(category_index=0)
        session.add(cursor_row)
        session.commit()
    index = cursor_row.category_index
    session.close()
    return index


def set_discovery_cursor(engine: Engine, index: int) -> None:
    """Update the discovery category index."""
    session = get_session(engine)
    cursor_row = session.query(DiscoveryCursor).first()
    if not cursor_row:
        cursor_row = DiscoveryCursor(category_index=index)
        session.add(cursor_row)
    else:
        cursor_row.category_index = index
    session.commit()
    session.close()


# === Hunter_Quota CRUD ===

def get_hunter_quota(engine: Engine, month_key: str) -> dict:
    """Get Hunter quota for a given month (e.g., '2026-09')."""
    session = get_session(engine)
    quota_row = session.query(HunterQuota).filter_by(month_key=month_key).first()
    if not quota_row:
        quota_row = HunterQuota(month_key=month_key, searches_used=0, verifications_used=0)
        session.add(quota_row)
        session.commit()
    result = {
        "month_key": quota_row.month_key,
        "searches_used": quota_row.searches_used,
        "verifications_used": quota_row.verifications_used,
    }
    session.close()
    return result


def increment_hunter_quota(engine: Engine, month_key: str, searches: int = 0, verifications: int = 0) -> None:
    """Increment Hunter quota counters."""
    session = get_session(engine)
    quota_row = session.query(HunterQuota).filter_by(month_key=month_key).first()
    if not quota_row:
        quota_row = HunterQuota(month_key=month_key, searches_used=searches, verifications_used=verifications)
    else:
        quota_row.searches_used += searches
        quota_row.verifications_used += verifications
    session.add(quota_row)
    session.commit()
    session.close()
