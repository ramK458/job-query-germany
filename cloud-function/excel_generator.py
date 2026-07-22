"""Excel workbook create/append for the AFA job scraper."""

import io
import logging

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# Blue underlined font for clickable links
_LINK_FONT = Font(color="0563C1", underline="single")

logger = logging.getLogger(__name__)

HEADERS = ["Role Title", "Job Title", "Company Name", "Location", "Salary Range", "Link", "Job ID", "Posted Date"]
WIDTHS = [22, 40, 30, 22, 14, 55, 14, 16]

_HF = Font(bold=True, color="FFFFFF", size=11)
_HFILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
_HA = Alignment(horizontal="center", vertical="center", wrap_text=True)
_CA = Alignment(vertical="center")
_BORDER = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)


def _sanitize(name: str) -> str:
    return "".join(c if c not in "[]:*?/\\" else "-" for c in name)[:31]


def _write_header(ws) -> None:
    for i, h in enumerate(HEADERS, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font, c.fill, c.alignment, c.border = _HF, _HFILL, _HA, _BORDER
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}1"


def _format_rows(ws, start: int, end: int) -> None:
    """Set column widths and apply borders to rows *start*-*end* (only new data on append)."""
    for col_idx, w in enumerate(WIDTHS, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = w
    for row in ws.iter_rows(min_row=start, max_row=end, min_col=1, max_col=len(HEADERS)):
        for cell in row:
            cell.alignment, cell.border = _CA, _BORDER


def _to_row(job: dict) -> list:
    return [job.get("search_term", ""), job.get("titel", ""), job.get("arbeitgeber", "N/A"),
            job.get("ort", "N/A"), "N/A", job.get("url", ""), job.get("refnr", ""), job.get("eintrittsdatum", "N/A")]


def _make_links(ws, start: int, end: int) -> None:
    """Convert plain-text URLs in column 6 (Link) to clickable hyperlinks."""
    for row in range(start, end + 1):
        cell = ws.cell(row=row, column=6)
        url = cell.value
        if url:
            cell.hyperlink = url
            cell.font = _LINK_FONT


def _existing_refnrs(ws) -> set[str]:
    refs: set[str] = set()
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=7, max_col=7, values_only=True):
        if row[0]:
            refs.add(str(row[0]).strip())
    return refs


def _to_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def create_new_workbook(groups_data: dict[str, list[dict]]) -> bytes:
    """Create a new workbook with one sheet per group, styled headers, and all data formatted."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, jobs in groups_data.items():
        ws = wb.create_sheet(title=_sanitize(name))
        _write_header(ws)
        for j in jobs:
            ws.append(_to_row(j))
        _format_rows(ws, 2, len(jobs) + 1)
        _make_links(ws, 2, len(jobs) + 1)
    logger.info("Created workbook with %d sheets", len(groups_data))
    return _to_bytes(wb)


def append_to_workbook(workbook_bytes: bytes, groups_data: dict[str, list[dict]]) -> bytes:
    """Append new jobs to existing workbook, deduplicating by refnr. Only formats new rows."""
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes))
    for name, new_jobs in groups_data.items():
        sn = _sanitize(name)
        is_new = sn not in wb.sheetnames
        ws = wb.create_sheet(title=sn) if is_new else wb[sn]
        if is_new:
            _write_header(ws)
        existing = _existing_refnrs(ws) if not is_new else set()
        start_row = ws.max_row + 1
        appended = 0
        for job in new_jobs:
            ref = job.get("refnr", "")
            if ref and ref in existing:
                continue
            ws.append(_to_row(job))
            if ref:
                existing.add(ref)
            appended += 1
        if appended:
            _format_rows(ws, start_row, ws.max_row)
            _make_links(ws, start_row, ws.max_row)
        logger.info("Sheet '%s': appended %d / %d jobs", sn, appended, len(new_jobs))
    return _to_bytes(wb)
