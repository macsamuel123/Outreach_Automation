import os
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from . import constants
from .domainutil import normalize_domain


def ensure_workbook(path: Path = constants.WORKBOOK_PATH) -> None:
    """Create workbook with all 4 tabs and headers if file doesn't exist.

    Idempotent: does nothing if the file already exists.
    """
    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    wb.remove(wb.active)  # Remove default blank sheet

    sheets_and_columns = [
        (constants.SHEET_LEADS_SOURCE, constants.LEADS_SOURCE_COLUMNS),
        (constants.SHEET_PARTNER_TRACKER, constants.PARTNER_TRACKER_COLUMNS),
        (constants.SHEET_SUPPRESSION_LIST, constants.SUPPRESSION_LIST_COLUMNS),
        (constants.SHEET_AUDIT_LOG, constants.AUDIT_LOG_COLUMNS),
        (constants.SHEET_REVIEW_QUEUE, constants.REVIEW_QUEUE_COLUMNS),
    ]

    for sheet_name, columns in sheets_and_columns:
        ws = wb.create_sheet(sheet_name)
        for col_idx, col_name in enumerate(columns, start=1):
            cell = ws.cell(row=1, column=col_idx)
            cell.value = col_name
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"

    wb.save(path)


def ensure_sheet(wb: Workbook, sheet_name: str, columns: list[str]) -> bool:
    """Ensure a single sheet exists on an already-open workbook. Idempotent;
    safe to call on every load(). Returns True iff newly created."""
    if sheet_name in wb.sheetnames:
        return False
    ws = wb.create_sheet(sheet_name)
    for col_idx, col_name in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.value = col_name
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    return True


def load(path: Path = constants.WORKBOOK_PATH) -> Workbook:
    """Ensure workbook exists and load it. Retrofits missing sheets."""
    from openpyxl import load_workbook

    ensure_workbook(path)
    wb = load_workbook(path)
    created_any = False
    for sheet_name, columns in (
        (constants.SHEET_REVIEW_QUEUE, constants.REVIEW_QUEUE_COLUMNS),
    ):
        if ensure_sheet(wb, sheet_name, columns):
            created_any = True
    if created_any:
        save(wb, path)
    return wb


def save(wb: Workbook, path: Path = constants.WORKBOOK_PATH) -> None:
    """Atomically save workbook to avoid half-written files.

    Writes to a temporary file first, then renames it to the real path.
    This protects against corruption if the process dies mid-save.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(".xlsx.tmp")

    try:
        wb.save(tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise


def read_rows(
    ws: Worksheet, columns: list[str]
) -> list[dict]:
    """Read all non-header rows from a worksheet.

    Returns a list of dicts where each dict has:
    - One key per column name in `columns`, with the cell value
    - '_row_num': the Excel row number (1-indexed), for later in-place updates

    Missing cells are treated as None/blank.
    """
    # Build column index from header row
    header_row = 1
    col_index = {}
    for col_idx in range(1, ws.max_column + 1):
        header_cell = ws.cell(row=header_row, column=col_idx)
        header_name = header_cell.value
        if header_name:
            col_index[header_name] = col_idx

    rows = []
    for row_num in range(header_row + 1, ws.max_row + 1):
        row_dict = {"_row_num": row_num}
        for col_name in columns:
            col_idx = col_index.get(col_name)
            if col_idx:
                cell_value = ws.cell(row=row_num, column=col_idx).value
                row_dict[col_name] = cell_value
            else:
                row_dict[col_name] = None
        rows.append(row_dict)

    return rows


def append_row(ws: Worksheet, columns: list[str], values: dict) -> int:
    """Append a new row to the worksheet.

    Sets values for the given columns; leaves other columns blank.
    Returns the new row number (1-indexed).
    """
    header_row = 1
    col_index = {}
    for col_idx in range(1, ws.max_column + 1):
        header_cell = ws.cell(row=header_row, column=col_idx)
        header_name = header_cell.value
        if header_name:
            col_index[header_name] = col_idx

    new_row_num = ws.max_row + 1

    for col_name in columns:
        col_idx = col_index.get(col_name)
        if col_idx and col_name in values:
            ws.cell(row=new_row_num, column=col_idx).value = values[col_name]

    return new_row_num


def update_cells(ws: Worksheet, row_num: int, columns: list[str], values: dict) -> None:
    """Update specific cells in an existing row.

    Only modifies cells for columns present in both `columns` and `values`.
    """
    header_row = 1
    col_index = {}
    for col_idx in range(1, ws.max_column + 1):
        header_cell = ws.cell(row=header_row, column=col_idx)
        header_name = header_cell.value
        if header_name:
            col_index[header_name] = col_idx

    for col_name in columns:
        if col_name in values:
            col_idx = col_index.get(col_name)
            if col_idx:
                ws.cell(row=row_num, column=col_idx).value = values[col_name]


def build_domain_index(rows: list[dict], domain_field: str = "website") -> set[str]:
    """Build a set of normalized domains from rows.

    Useful for deduplication and suppression checks.
    """
    domains = set()
    for row in rows:
        domain = normalize_domain(row.get(domain_field, ""))
        if domain:
            domains.add(domain)
    return domains


def build_email_index(rows: list[dict], email_field: str = "email") -> set[str]:
    """Build a set of lowercase emails from rows."""
    emails = set()
    for row in rows:
        email = row.get(email_field, "")
        if email:
            emails.add(email.lower())
    return emails


def is_suppressed(
    email: str, domain: str, suppression_rows: list[dict]
) -> bool:
    """Check if an email or domain is in the suppression list.

    Returns True if email (case-insensitive) or domain (normalized) is suppressed.
    """
    email_index = build_email_index(suppression_rows, "email")
    domain_index = build_domain_index(suppression_rows, "domain")

    email_normalized = email.lower() if email else ""
    domain_normalized = normalize_domain(domain) if domain else ""

    return email_normalized in email_index or domain_normalized in domain_index
