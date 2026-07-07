from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from flask import current_app

from ..repository import (
    SERVICE_TYPES,
    employee_date_summary,
    employee_monthly_summary,
    fetch_settings,
    get_employee,
    list_employees,
    output_per_person_rows,
    output_summary_grand_totals,
    signatories_for_report,
)


REGISTRATION_SERVICES = [
    "National ID Registration",
    "Issuance of National ID in Paper Form Only",
    "National ID Registration and Assistance in Generating the Digital National ID",
    "Assistance in Generating the Digital National ID Only",
    "TRN Retrieval",
    "TRN Retrieval and Issuance of National ID in Paper Form Only",
    "Authentication",
    "Recapture",
    "Rejected Packet",
    "Authentication and Issuance of National ID in Paper Form",
]


def _reportlab_modules():
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import mm
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PDF export requires the 'reportlab' package. Run pip install -r requirements.txt first."
        ) from exc

    return colors, A4, landscape, mm, ImageReader, canvas


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_")


def _force_canvas_all_caps(c) -> None:
    """Render all PDF text in uppercase for consistency."""
    orig_draw = c.drawString
    orig_center = c.drawCentredString
    orig_right = c.drawRightString

    def _caps(value):
        return value.upper() if isinstance(value, str) else value

    c.drawString = lambda x, y, text, *args, **kwargs: orig_draw(x, y, _caps(text), *args, **kwargs)
    c.drawCentredString = lambda x, y, text, *args, **kwargs: orig_center(x, y, _caps(text), *args, **kwargs)
    c.drawRightString = lambda x, y, text, *args, **kwargs: orig_right(x, y, _caps(text), *args, **kwargs)


def _draw_page_number(c, width: float, mm: float) -> None:
    """Draw page number at bottom-right."""
    c.setFont("Helvetica", 8)
    c.drawRightString(width - 12 * mm, 8 * mm, f"Page {c.getPageNumber()}")


def _logo_path() -> Path | None:
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    # Prefer explicitly named PSA logo if present, then generic logo.* files
    candidates = ["psa_logo.png", "psa_logo.jpg", "psa_logo.jpeg", "logo.png", "logo.jpg", "logo.jpeg"]
    for name in candidates:
        candidate = upload_dir / name
        if candidate.exists():
            return candidate
    # Fallback to any file matching logo* in the upload dir
    for ext in ("png", "jpg", "jpeg"):
        for p in upload_dir.glob(f"logo*.{ext}"):
            return p
    return None


def _fixed_logo_path(filename: str) -> Path | None:
    base = Path(current_app.root_path).parent / "logo"
    # Try the exact filename and a few common variations
    variations = [
        filename,
        filename.replace(" ", "_"),
        filename.lower(),
        filename.lower().replace(" ", "_"),
        "psa_logo.png",
        "PSA and National ID logo.png",
        "National ID.png",
        "national id.png",
        "PSA.png",
        "psa.png",
    ]
    for name in variations:
        candidate = base / name
        if candidate.exists():
            return candidate
    # Fallback: return any file that looks like a logo
    if base.exists():
        for p in base.iterdir():
            if p.is_file() and any(tok in p.name.lower() for tok in ("psa", "bagong", "logo")):
                return p
    return None


def _wrap_text(c, text: str, font_name: str, font_size: int, max_width: float) -> list[str]:
    words = str(text).split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        next_line = f"{current} {word}"
        if c.stringWidth(next_line, font_name, font_size) <= max_width:
            current = next_line
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_logos(
    c,
    bounds: tuple[float, float],
    mm,
    ImageReader,
    *,
    top_offset_mm: float = 16.0,
    logo_width_mm: float = 30.0,
    logo_height_mm: float = 30.0,
) -> None:
    """Draw left/right PSA logos. Smaller `top_offset_mm` places logos higher (closer to page top)."""
    left_logo = _fixed_logo_path("National ID.png")
    right_logo = _fixed_logo_path("PSA.png")
    width, height = bounds
    top = height - top_offset_mm * mm
    logo_width = logo_width_mm * mm
    logo_height = logo_height_mm * mm
    if left_logo and left_logo.exists():
        c.drawImage(
            ImageReader(str(left_logo)),
            20 * mm,
            top - logo_height,
            width=logo_width,
            height=logo_height,
            preserveAspectRatio=True,
            mask="auto",
        )
    if right_logo and right_logo.exists():
        c.drawImage(
            ImageReader(str(right_logo)),
            width - 20 * mm - logo_width,
            top - logo_height,
            width=logo_width,
            height=logo_height,
            preserveAspectRatio=True,
            mask="auto",
        )


def _draw_output_summary_page_letterhead(
    c,
    width: float,
    height: float,
    mm: float,
    ImageReader,
    settings: dict,
    *,
    logo_top_mm: float = 5.0,
    logo_size_mm: float = 22.0,
) -> tuple[float, float]:
    """Logos + Republic / PSA org name / Employee Output Summary (repeated on every page)."""
    _draw_logos(
        c,
        (width, height),
        mm,
        ImageReader,
        top_offset_mm=logo_top_mm,
        logo_width_mm=logo_size_mm,
        logo_height_mm=logo_size_mm,
    )
    logo_top_y = height - logo_top_mm * mm
    logo_bottom_y = logo_top_y - logo_size_mm * mm
    y = logo_top_y - 8 * mm
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, y, "Republic of the Philippines")
    org_name = settings.get("organization_name", "PHILIPPINE STATISTICS AUTHORITY")
    org_lines = _wrap_text(c, org_name, "Helvetica-Bold", 12, width - 100 * mm)
    y -= 6 * mm
    for line in org_lines:
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(width / 2, y, line)
        y -= 6.5 * mm
    title_lines = _wrap_text(c, "Employee Output Summary", "Helvetica-Bold", 14, width - 100 * mm)
    last_title_baseline = y
    for line in title_lines:
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(width / 2, y, line)
        last_title_baseline = y
        y -= 7.5 * mm
    return logo_bottom_y, last_title_baseline


def _output_summary_continuation_table_header_bottom(
    logo_bottom_y: float,
    last_title_baseline: float,
    header_row_h: float,
    mm: float,
) -> float:
    """Table header bottom Y on continuation pages (letterhead only, no meta lines)."""
    header_bottom = min(logo_bottom_y, last_title_baseline - 3 * mm)
    gap = 10 * mm
    return header_bottom - gap - header_row_h


def _header_font_size_for_cell(cell_w: float, mm: float) -> float:
    """Narrow columns need smaller type so wrapped headers stay readable."""
    if cell_w < 12 * mm:
        return 6.5
    if cell_w < 16 * mm:
        return 7.5
    if cell_w < 22 * mm:
        return 8.0
    return 8.5


def _draw_wrapped_centered_header_cell(
    c,
    x_left: float,
    y_bottom: float,
    cell_w: float,
    header_row_h: float,
    text: str,
    font_name: str,
    font_size: float,
    mm: float,
) -> None:
    """Multi-line centered header text inside a table header cell (top-aligned block)."""
    pad = 1.5 * mm
    max_w = max(cell_w - 2 * pad, 4 * mm)
    c.setFont(font_name, font_size)
    lines = _wrap_text(c, text, font_name, font_size, max_w)
    leading = max(2.8 * mm, min(3.8 * mm, font_size * 0.42 * mm))
    max_lines = max(1, int((header_row_h - 2 * pad) / leading))
    lines = lines[:max_lines]
    y_line = y_bottom + header_row_h - pad - max(2.0 * mm, font_size * 0.35 * mm)
    for line in lines:
        c.drawCentredString(x_left + cell_w / 2, y_line, line)
        y_line -= leading


def _draw_output_summary_header_row(
    c,
    left: float,
    y_top: float,
    col_widths: list[float],
    headers: list[str],
    header_row_h: float,
    colors,
    mm: float,
) -> None:
    """Draw bordered header row with wrapped labels (taller than data rows)."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    x = left
    for w_cell in col_widths:
        c.rect(x, y_top, w_cell, header_row_h, stroke=1, fill=0)
        x += w_cell
    x = left
    for header, w_cell in zip(headers, col_widths):
        fs = _header_font_size_for_cell(w_cell, mm)
        _draw_wrapped_centered_header_cell(
            c, x, y_top, w_cell, header_row_h, header, "Helvetica-Bold", fs, mm
        )
        x += w_cell


def _draw_output_summary_grand_total_row(
    c,
    left: float,
    y_row_bottom: float,
    col_widths: list[float],
    service_types: list[str],
    grand: dict,
    date_w: float,
    service_w: float,
    total_w: float,
    cumulative_w: float,
    row_h: float,
    colors,
    mm: float,
) -> None:
    """Bold footer row: Grand Total + column sums for the filtered date range."""
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.75)
    x = left
    for w_cell in col_widths:
        c.rect(x, y_row_bottom, w_cell, row_h, stroke=1, fill=0)
        x += w_cell
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(left + date_w / 2, y_row_bottom + 2.6 * mm, "Grand Total")
    x = left + date_w
    gs = grand["services"]
    for service in service_types:
        c.drawRightString(x + service_w - 2 * mm, y_row_bottom + 2.6 * mm, str(gs.get(service, 0)))
        x += service_w
    c.drawRightString(x + total_w - 2 * mm, y_row_bottom + 2.6 * mm, str(grand["total"]))
    x += total_w
    c.drawRightString(x + cumulative_w - 2 * mm, y_row_bottom + 2.6 * mm, str(grand["cumulative"]))


def generate_employee_report_by_date(
    employee_id: int,
    start_date: str,
    end_date: str,
    report_type: str,
) -> Path:
    colors, A4, _landscape, mm, ImageReader, canvas = _reportlab_modules()
    employee = get_employee(employee_id)
    if employee is None:
        raise ValueError("Employee not found.")

    settings = fetch_settings()
    signatories = signatories_for_report(report_type)
    rows = employee_date_summary(employee_id, start_date, end_date, report_type)

    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    filename = f"{start_date}_to_{end_date}_{_safe_filename(employee['full_name'])}_{report_type}.pdf"
    pdf_path = output_dir / filename

    grouped = defaultdict(lambda: {"quantity": 0, "activities": [], "province": "", "city": ""})
    service_totals = defaultdict(int)
    for row in rows:
        grouped[row["work_date"]]["quantity"] += row["quantity"]
        if row["activity_type"]:
            grouped[row["work_date"]]["activities"].append(row["activity_type"])
            service_totals[row["activity_type"]] += row["quantity"]
        if row["remarks"]:
            grouped[row["work_date"]]["activities"].append(row["remarks"])
        grouped[row["work_date"]]["province"] = row["province"] or employee["province"] or ""
        grouped[row["work_date"]]["city"] = row["city_municipality"] or employee["city_municipality"] or ""

    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    _force_canvas_all_caps(c)
    width, height = A4

    _draw_header(
        c,
        width,
        height,
        mm=mm,
        ImageReader=ImageReader,
        settings=settings,
        employee=employee,
        date_label=_date_label(start_date, end_date),
        report_type=report_type,
        province=next((v["province"] for v in grouped.values() if v["province"]), employee["province"] or ""),
        city=next((v["city"] for v in grouped.values() if v["city"]), employee["city_municipality"] or ""),
    )
    _draw_table(c, grouped, start_date, end_date, report_type, colors=colors, mm=mm)
    _draw_service_summary(c, service_totals, report_type, colors=colors, mm=mm)
    _draw_signatories(c, width, signatories, mm=mm)
    c.save()
    return pdf_path


def generate_bulk_reports_by_date(start_date: str, end_date: str, report_type: str) -> Path:
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    zip_path = output_dir / f"{start_date}_to_{end_date}_{report_type}_employee_reports.zip"
    employee_rows = list_employees()

    with ZipFile(zip_path, "w") as archive:
        for employee in employee_rows:
            if not employee["active"]:
                continue
            pdf_path = generate_employee_report_by_date(employee["id"], start_date, end_date, report_type)
            archive.write(pdf_path, arcname=pdf_path.name)
    return zip_path


def _draw_header(c, width, height, mm, ImageReader, settings, employee, date_label, report_type, province, city):
    top = height - 32 * mm  # Increased spacing to avoid logo overlap
    logo = _logo_path()
    if logo:
        c.drawImage(
            ImageReader(str(logo)),
            20 * mm,
            top - 10 * mm,
            width=20 * mm,
            height=20 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )

    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, top, "Republic of the Philippines")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(
        width / 2,
        top - 5 * mm,
        settings.get("organization_name", "PHILIPPINE STATISTICS AUTHORITY"),
    )
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(
        width / 2,
        top - 11 * mm,
        settings.get("report_title", "Daily Accomplishment Report"),
    )
    c.setFont("Helvetica", 10)
    c.drawString(25 * mm, top - 22 * mm, f"Province: {province or '________________'}")
    c.drawString(25 * mm, top - 28 * mm, f"City/Municipality: {city or '________________'}")
    c.drawString(25 * mm, top - 34 * mm, f"Date Filter: {date_label}")
    c.drawString(25 * mm, top - 40 * mm, f"Employee: {employee['full_name']}")
    c.drawString(25 * mm, top - 46 * mm, f"Position: {employee['position'] or '________________'}")
    c.drawRightString(width - 20 * mm, top - 46 * mm, f"Category: {report_type.title()}")


def _draw_table(c, grouped, start_date, end_date, report_type, colors, mm):
    left = 20 * mm
    top = 188 * mm
    row_h = 10 * mm
    col_widths = [24 * mm, 24 * mm, 24 * mm, 100 * mm]
    headers = ["Date (mm/dd)", f"Daily {report_type.title()}", "Cumulative", "Remarks / Activities"]

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    x = left
    for width in col_widths:
        c.rect(x, top, width, row_h, stroke=1, fill=0)
        x += width

    c.setFont("Helvetica-Bold", 8)
    x = left
    for header, width in zip(headers, col_widths):
        lines = _wrap_text(c, header, "Helvetica-Bold", 8, width - 4 * mm)
        y_text = top + row_h - 3.5 * mm
        for line in lines:
            c.drawCentredString(x + width / 2, y_text, line)
            y_text -= 4.2 * mm
        x += width

    c.setFont("Helvetica", 8)
    cumulative = 0
    current = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    y = top - row_h
    while current <= end and y > 56 * mm:
        work_date = current.strftime("%Y-%m-%d")
        entry = grouped.get(work_date, {"quantity": 0, "activities": []})
        cumulative += entry["quantity"]
        remarks = "; ".join(dict.fromkeys([item for item in entry["activities"] if item]))[:100]

        x = left
        for width in col_widths:
            c.rect(x, y, width, row_h, stroke=1, fill=0)
            x += width

        c.drawCentredString(left + col_widths[0] / 2, y + 4 * mm, current.strftime("%m/%d"))
        c.drawRightString(left + col_widths[0] + col_widths[1] - 3 * mm, y + 4 * mm, str(entry["quantity"]))
        c.drawRightString(left + col_widths[0] + col_widths[1] + col_widths[2] - 3 * mm, y + 4 * mm, str(cumulative))
        c.drawString(left + col_widths[0] + col_widths[1] + col_widths[2] + 2 * mm, y + 4 * mm, remarks)
        y -= row_h
        current += timedelta(days=1)

    c.setFont("Helvetica-Bold", 9)
    c.drawString(left, y - 2 * mm, f"Total {report_type.title()}: {cumulative}")


def _draw_service_summary(c, service_totals, report_type, colors, mm):
    left = 154 * mm
    top = 188 * mm
    row_h = 6.5 * mm
    name_w = 42 * mm
    count_w = 12 * mm

    labels = REGISTRATION_SERVICES if report_type.lower() == "registration" else list(service_totals.keys())
    if not labels:
        labels = ["No activity"]

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.rect(left, top, name_w + count_w, row_h, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(left + 2 * mm, top + 2.2 * mm, "Service Summary")
    c.drawRightString(left + name_w + count_w - 2 * mm, top + 2.2 * mm, "Count")

    y = top - row_h
    total = 0
    c.setFont("Helvetica", 7)
    for label in labels[:18]:
        count = service_totals.get(label, 0)
        total += count
        c.rect(left, y, name_w + count_w, row_h, stroke=1, fill=0)
        c.line(left + name_w, y, left + name_w, y + row_h)
        c.drawString(left + 1.5 * mm, y + 2.1 * mm, label[:33])
        c.drawRightString(left + name_w + count_w - 1.5 * mm, y + 2.1 * mm, str(count))
        y -= row_h

    c.setFont("Helvetica-Bold", 8)
    c.rect(left, y, name_w + count_w, row_h, stroke=1, fill=0)
    c.line(left + name_w, y, left + name_w, y + row_h)
    c.drawString(left + 1.5 * mm, y + 2.1 * mm, "Total")
    c.drawRightString(left + name_w + count_w - 1.5 * mm, y + 2.1 * mm, str(total))


def _draw_signatories(
    c,
    width,
    signatories,
    mm,
    prepared_name: str | None = None,
    prepared_position: str | None = None,
    *,
    default_prepared_position: str = "Prepared by",
    default_verified_position: str = "Verified by",
    footer_anchor_mm: float = 30.0,
    label_size: float = 10,
    position_size: float = 9,
    verified_name_override: str | None = None,
    verified_position_override: str | None = None,
):
    prepared = signatories.get("prepared_by") or {}
    verified = signatories.get("verified_by") or {}
    display_prepared = (prepared_name or prepared.get("name") or "").strip() or "________________"
    ppos = (prepared_position or "").strip() or (prepared.get("position") or "").strip() or default_prepared_position
    if verified_name_override is not None:
        vname = verified_name_override
        vpos = verified_position_override or default_verified_position
    else:
        vname = (verified.get("name") or "").strip() or "________________"
        vpos = (verified.get("position") or "").strip() or default_verified_position

    # Fixed footer position at bottom of page (smaller anchor = block sits lower on the page)
    bottom_y = footer_anchor_mm * mm
    sig_w = min(80 * mm, (width - 100 * mm) / 2)
    left_x = 30 * mm
    right_x = width - 30 * mm - sig_w

    # Prepared by block
    c.setFont("Helvetica", label_size)
    c.drawString(left_x, bottom_y + 16 * mm, "Prepared by:")
    c.line(left_x, bottom_y + 13 * mm, left_x + sig_w, bottom_y + 13 * mm)
    c.setFont("Helvetica-Bold", label_size)
    c.drawString(left_x, bottom_y + 5 * mm, display_prepared)
    c.setFont("Helvetica", position_size)
    c.drawString(left_x, bottom_y - 1 * mm, ppos)

    # Verified by block
    c.setFont("Helvetica", label_size)
    c.drawString(right_x, bottom_y + 16 * mm, "Verified as correct by:")
    c.line(right_x, bottom_y + 13 * mm, right_x + sig_w, bottom_y + 13 * mm)
    c.setFont("Helvetica-Bold", label_size)
    c.drawString(right_x, bottom_y + 5 * mm, vname)
    c.setFont("Helvetica", position_size)
    c.drawString(right_x, bottom_y - 1 * mm, vpos)


def _date_label(start_date: str, end_date: str) -> str:
    if start_date == end_date:
        return datetime.strptime(start_date, "%Y-%m-%d").strftime("%B %d, %Y")
    start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%B %d, %Y")
    end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%B %d, %Y")
    return f"{start} to {end}"


def _preview_date_filter_line(start_date: str, end_date: str) -> str:
    """Human-readable date filter for PDF (aligned with output summary preview)."""
    sd = (start_date or "").strip()
    ed = (end_date or "").strip()
    if sd and ed:
        return f"{sd} to {ed}"
    if sd:
        return f"From {sd}"
    if ed:
        return f"Until {ed}"
    return "All dates"


def _output_report_filename_segment(start_date: str, end_date: str) -> str:
    sd = (start_date or "").strip()
    ed = (end_date or "").strip()
    if sd and ed:
        return f"{sd}_to_{ed}"
    if sd:
        return f"from_{_safe_filename(sd)}"
    if ed:
        return f"until_{_safe_filename(ed)}"
    return "all_dates"


def generate_output_summary_report(
    rows: list[dict],
    service_types: list[str],
    start_date: str,
    end_date: str,
    employee_name: str | None = None,
    prepared_position: str | None = None,
) -> Path:
    colors, A4, landscape, mm, ImageReader, canvas = _reportlab_modules()
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    output_dir.mkdir(exist_ok=True)
    settings = fetch_settings()
    date_filter_display = _preview_date_filter_line(start_date, end_date)

    filename = f"output_summary_{_output_report_filename_segment(start_date, end_date)}"
    if employee_name:
        filename += f"_{_safe_filename(employee_name)}"
    filename += ".pdf"
    pdf_path = output_dir / filename

    c = canvas.Canvas(str(pdf_path), pagesize=landscape(A4))
    _force_canvas_all_caps(c)
    width, height = landscape(A4)

    # Table / meta horizontal origin (same left edge)
    left = 20 * mm
    # Fixed header band: logos + centered titles share one vertical strip; meta aligns with table at `left`
    _logo_top_mm = 5.0
    _logo_size_mm = 22.0
    _header_row_h = 24 * mm
    _data_row_h = 7 * mm
    meta_x = left
    logo_bottom_y, last_title_baseline = _draw_output_summary_page_letterhead(
        c,
        width,
        height,
        mm,
        ImageReader,
        settings,
        logo_top_mm=_logo_top_mm,
        logo_size_mm=_logo_size_mm,
    )

    # Meta sits just below the lower of (logo band, last title baseline) — aligns with table at `left`
    header_bottom = min(logo_bottom_y, last_title_baseline - 3 * mm)
    meta_y1 = header_bottom - 6 * mm
    c.setFont("Helvetica", 10)
    c.drawString(meta_x, meta_y1, f"Date Filter: {date_filter_display}")
    c.drawString(meta_x, meta_y1 - 6 * mm, f"Employee: {employee_name or 'All Employees'}")
    right_margin = 18 * mm
    date_w = 20 * mm
    total_w = 18 * mm
    cumulative_w = 18 * mm
    remaining_width = width - left - right_margin - date_w - total_w - cumulative_w
    service_w = max(14 * mm, remaining_width / max(1, len(service_types)))
    col_widths = [date_w] + [service_w] * len(service_types) + [total_w, cumulative_w]
    headers = ["Date"] + service_types + ["Total", "Cumulative"]

    meta_employee_baseline = meta_y1 - 6 * mm
    y_table_header_bottom = meta_employee_baseline - 8 * mm - _header_row_h

    _draw_output_summary_header_row(
        c, left, y_table_header_bottom, col_widths, headers, _header_row_h, colors, mm
    )

    c.setFont("Helvetica", 8)
    y = y_table_header_bottom - _data_row_h
    _min_y_for_row = 52 * mm
    for row in rows:
        if y < _min_y_for_row:
            _draw_page_number(c, width, mm)
            c.showPage()
            logo_bottom_y, last_title_baseline = _draw_output_summary_page_letterhead(
                c,
                width,
                height,
                mm,
                ImageReader,
                settings,
                logo_top_mm=_logo_top_mm,
                logo_size_mm=_logo_size_mm,
            )
            y_top = _output_summary_continuation_table_header_bottom(
                logo_bottom_y, last_title_baseline, _header_row_h, mm
            )
            _draw_output_summary_header_row(
                c, left, y_top, col_widths, headers, _header_row_h, colors, mm
            )
            c.setFont("Helvetica", 8)
            y = y_top - _data_row_h

        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        x = left
        for w_cell in col_widths:
            c.rect(x, y, w_cell, _data_row_h, stroke=1, fill=0)
            x += w_cell

        c.drawCentredString(left + date_w / 2, y + 2.5 * mm, row["date"])
        x = left + date_w
        for service in service_types:
            c.drawRightString(x + service_w - 2 * mm, y + 2.5 * mm, str(row.get(service, 0)))
            x += service_w
        c.drawRightString(x + total_w - 2 * mm, y + 2.5 * mm, str(row["total"]))
        x += total_w
        c.drawRightString(x + cumulative_w - 2 * mm, y + 2.5 * mm, str(row["cumulative"]))
        y -= _data_row_h

    _grand_row_h = 8 * mm
    if rows:
        grand = output_summary_grand_totals(rows, service_types)
        if y < _min_y_for_row:
            _draw_page_number(c, width, mm)
            c.showPage()
            logo_bottom_y, last_title_baseline = _draw_output_summary_page_letterhead(
                c,
                width,
                height,
                mm,
                ImageReader,
                settings,
                logo_top_mm=_logo_top_mm,
                logo_size_mm=_logo_size_mm,
            )
            y_top = _output_summary_continuation_table_header_bottom(
                logo_bottom_y, last_title_baseline, _header_row_h, mm
            )
            _draw_output_summary_header_row(
                c, left, y_top, col_widths, headers, _header_row_h, colors, mm
            )
            y = y_top - _grand_row_h
        _draw_output_summary_grand_total_row(
            c,
            left,
            y,
            col_widths,
            service_types,
            grand,
            date_w,
            service_w,
            total_w,
            cumulative_w,
            _grand_row_h,
            colors,
            mm,
        )

    signatories = signatories_for_report("output")
    _draw_signatories(
        c,
        width,
        signatories,
        mm,
        prepared_name=employee_name,
        prepared_position=prepared_position,
        default_prepared_position="National ID Registration",
        default_verified_position="Focal Person",
        footer_anchor_mm=14.0,
    )
    _draw_page_number(c, width, mm)

    c.save()
    return pdf_path


def generate_all_employees_output_reports_by_date(start_date: str, end_date: str) -> Path:
    """Generate individual output reports for all employees and zip them (same PDF as Download PDF / preview)."""
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    output_dir.mkdir(exist_ok=True)
    employees = list_employees()
    seg = _output_report_filename_segment(start_date, end_date)
    zip_path = output_dir / f"{seg}_all_employees_output_reports.zip"

    with ZipFile(zip_path, "w") as archive:
        for employee in employees:
            if not employee["active"]:
                continue
            filters: dict = {"employee_id": employee["id"]}
            if (start_date or "").strip():
                filters["start_date"] = start_date
            if (end_date or "").strip():
                filters["end_date"] = end_date
            rows = output_per_person_rows(filters)
            if not rows:
                continue
            pdf_path = generate_output_summary_report(
                rows,
                SERVICE_TYPES,
                start_date,
                end_date,
                employee["full_name"],
                employee["position"],
            )
            archive.write(pdf_path, arcname=pdf_path.name)
            pdf_path.unlink(missing_ok=True)

    return zip_path


def _focal_person_info() -> tuple[str, str]:
    for employee in list_employees():
        position = (employee["position"] or "").strip().lower()
        if employee["active"] and position == "focal person":
            return (employee["full_name"] or "").strip(), (employee["position"] or "").strip() or "Focal Person"
    return "", "Focal Person"


def generate_schedule_report(
    rows: list[dict],
    start_date: str = "",
    end_date: str = "",
    status: str = "",
) -> Path:
    colors, A4, landscape, mm, ImageReader, canvas = _reportlab_modules()
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    output_dir.mkdir(exist_ok=True)
    settings = fetch_settings()

    filename = "schedule_report"
    if (start_date or "").strip() and (end_date or "").strip():
        filename += f"_{_safe_filename(start_date)}_to_{_safe_filename(end_date)}"
    elif (start_date or "").strip():
        filename += f"_from_{_safe_filename(start_date)}"
    elif (end_date or "").strip():
        filename += f"_until_{_safe_filename(end_date)}"
    if (status or "").strip():
        filename += f"_{_safe_filename(status)}"
    filename += ".pdf"
    pdf_path = output_dir / filename

    c = canvas.Canvas(str(pdf_path), pagesize=landscape(A4))
    _force_canvas_all_caps(c)
    width, height = landscape(A4)

    # Letterhead (same logo positioning style as other reports)
    _draw_logos(
        c,
        (width, height),
        mm,
        ImageReader,
        top_offset_mm=5.0,
        logo_width_mm=22.0,
        logo_height_mm=22.0,
    )
    y = height - 13 * mm
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, y, "Republic of the Philippines")
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, y, settings.get("organization_name", "PHILIPPINE STATISTICS AUTHORITY"))
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, y, "Schedule of Assignments")

    meta_y = y - 9 * mm
    c.setFont("Helvetica", 10)
    date_filter = "All dates"
    if (start_date or "").strip() and (end_date or "").strip():
        date_filter = f"{start_date} to {end_date}"
    elif (start_date or "").strip():
        date_filter = f"From {start_date}"
    elif (end_date or "").strip():
        date_filter = f"Until {end_date}"
    c.drawString(20 * mm, meta_y, f"Date Filter: {date_filter}")
    c.drawString(20 * mm, meta_y - 6 * mm, f"Status: {(status or 'All').strip() or 'All'}")

    left = 20 * mm
    right = width - 20 * mm
    available_w = right - left
    col_widths = [
        22 * mm,  # Date
        34 * mm,  # City
        42 * mm,  # RKO
        42 * mm,  # RA
        58 * mm,  # Event
        20 * mm,  # Status
        20 * mm,  # Vehicle
    ]
    total_w = sum(col_widths)
    if total_w > available_w:
        scale = available_w / total_w
        col_widths = [w * scale for w in col_widths]
    headers = [
        "Date",
        "City / Municipality",
        "Assigned Registration Kit Operator",
        "Assigned Registration Assistant",
        "Event / Place / Activity",
        "Status",
        "Vehicle",
    ]
    header_h = 15 * mm
    row_h = 8 * mm
    # Keep table clearly below Date Filter / Status lines.
    y_top = meta_y - 24 * mm

    def draw_header(at_y: float) -> None:
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        x = left
        for w_cell in col_widths:
            c.rect(x, at_y, w_cell, header_h, stroke=1, fill=0)
            x += w_cell
        x = left
        for label, w_cell in zip(headers, col_widths):
            fs = _header_font_size_for_cell(w_cell, mm)
            _draw_wrapped_centered_header_cell(
                c, x, at_y, w_cell, header_h, label, "Helvetica-Bold", fs, mm
            )
            x += w_cell

    draw_header(y_top)
    y_row = y_top - row_h
    min_y = 36 * mm
    c.setFont("Helvetica", 8)

    for row in rows:
        if y_row < min_y:
            _draw_page_number(c, width, mm)
            c.showPage()
            _draw_logos(
                c,
                (width, height),
                mm,
                ImageReader,
                top_offset_mm=5.0,
                logo_width_mm=22.0,
                logo_height_mm=22.0,
            )
            c.setFont("Helvetica-Bold", 12)
            c.drawCentredString(width / 2, height - 18 * mm, "Schedule of Assignments")
            y_top = height - 60 * mm
            draw_header(y_top)
            c.setFont("Helvetica", 8)
            y_row = y_top - row_h

        rko_names = ", ".join(row.get("assigned_rko_names") or []) or "-"
        ra_names = ", ".join(row.get("assigned_ra_names") or []) or "-"
        event = (row.get("event_place_activity") or "-").strip()
        values = [
            row.get("schedule_date") or "",
            row.get("city_municipality") or "",
            rko_names,
            ra_names,
            event,
            row.get("status") or "Pending",
            row.get("vehicle") or "",
        ]

        x = left
        for val, w_cell in zip(values, col_widths):
            c.rect(x, y_row, w_cell, row_h, stroke=1, fill=0)
            text = str(val)
            max_w = w_cell - 3 * mm
            if c.stringWidth(text, "Helvetica", 8) > max_w:
                while text and c.stringWidth(text + "...", "Helvetica", 8) > max_w:
                    text = text[:-1]
                text = (text + "...") if text else "..."
            c.drawString(x + 1.5 * mm, y_row + 2.4 * mm, text)
            x += w_cell
        y_row -= row_h

    focal_name, focal_position = _focal_person_info()
    focal_name = focal_name or "________________"
    c.setFont("Helvetica", 10)
    c.drawString(25 * mm, 24 * mm, "Prepared by:")
    c.line(25 * mm, 21 * mm, 95 * mm, 21 * mm)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(25 * mm, 14 * mm, focal_name)
    c.setFont("Helvetica", 9)
    c.drawString(25 * mm, 9 * mm, focal_position)
    _draw_page_number(c, width, mm)

    c.save()
    return pdf_path


def _locator_month_label(start_date: str, end_date: str) -> str:
    sd = (start_date or "").strip()
    ed = (end_date or "").strip()
    if sd and ed:
        try:
            ds = datetime.strptime(sd, "%Y-%m-%d")
            de = datetime.strptime(ed, "%Y-%m-%d")
            if ds.year == de.year and ds.month == de.month:
                return ds.strftime("%B %Y")
            return f"{ds.strftime('%B %d, %Y')} to {de.strftime('%B %d, %Y')}"
        except ValueError:
            return f"{sd} to {ed}"
    if sd:
        try:
            return datetime.strptime(sd, "%Y-%m-%d").strftime("%B %Y")
        except ValueError:
            return sd
    if ed:
        try:
            return datetime.strptime(ed, "%Y-%m-%d").strftime("%B %Y")
        except ValueError:
            return ed
    return "________________"


def _draw_locator_chart_page(c, width, height, mm, ImageReader, employee: dict, rows: list[dict], month_label: str) -> None:
    _draw_logos(
        c,
        (width, height),
        mm,
        ImageReader,
        top_offset_mm=6.0,
        logo_width_mm=20.0,
        logo_height_mm=20.0,
    )
    # Tighter ("dikit") header line spacing.
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 14 * mm, "Philippine Statistics Authority")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, height - 20 * mm, "National ID Mobile Registration")
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width / 2, height - 30 * mm, "LOCATOR'S CHART")

    left = 10 * mm
    right = width - 10 * mm
    info_top = height - 40 * mm
    c.setFont("Helvetica", 11)
    c.drawString(left, info_top, "Name:")
    c.line(left + 38 * mm, info_top - 1 * mm, left + 108 * mm, info_top - 1 * mm)
    c.drawString(left + 40 * mm, info_top + 0.8 * mm, (employee.get("full_name") or "").strip())

    c.drawString(left, info_top - 8 * mm, "Position:")
    c.line(left + 38 * mm, info_top - 9 * mm, left + 108 * mm, info_top - 9 * mm)
    c.drawString(left + 40 * mm, info_top - 7.2 * mm, (employee.get("position") or "").strip())

    c.drawString(left, info_top - 16 * mm, "For the month of")
    c.line(left + 38 * mm, info_top - 17 * mm, left + 108 * mm, info_top - 17 * mm)
    c.drawString(left + 40 * mm, info_top - 15.2 * mm, month_label)

    table_top = info_top - 24 * mm
    row_h = 7 * mm
    date_w = 40 * mm
    place_w = (right - left) - date_w

    c.setLineWidth(0.8)
    c.rect(left, table_top, date_w, row_h, stroke=1, fill=0)
    c.rect(left + date_w, table_top, place_w, row_h, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(left + date_w / 2, table_top + 2.2 * mm, "Date")
    c.drawCentredString(left + date_w + place_w / 2, table_top + 2.2 * mm, "Place")

    sorted_rows = sorted(rows, key=lambda r: (r.get("schedule_date") or "", r.get("city_municipality") or ""))
    max_rows = 15
    y = table_top - row_h
    c.setFont("Helvetica", 10)
    for idx in range(max_rows):
        c.rect(left, y, date_w, row_h, stroke=1, fill=0)
        c.rect(left + date_w, y, place_w, row_h, stroke=1, fill=0)
        if idx < len(sorted_rows):
            row = sorted_rows[idx]
            date_val = (row.get("schedule_date") or "").strip()
            event_place = (row.get("event_place_activity") or "").strip()
            city = (row.get("city_municipality") or "").strip()
            if event_place and city:
                place = f"{event_place} | {city}"
            else:
                place = event_place or city
            c.drawCentredString(left + date_w / 2, y + 2.1 * mm, date_val)
            if c.stringWidth(place, "Helvetica", 10) > place_w - 4 * mm:
                while place and c.stringWidth(place + "...", "Helvetica", 10) > place_w - 4 * mm:
                    place = place[:-1]
                place = (place + "...") if place else "..."
            c.drawString(left + date_w + 2 * mm, y + 2.1 * mm, place)
        y -= row_h

    focal_name, focal_position = _focal_person_info()
    focal_name = focal_name or "________________"
    footer_y = 14 * mm
    block_w = 90 * mm
    left_x = left
    right_x = width - left - block_w

    c.setFont("Helvetica", 10)
    c.drawString(left_x, footer_y + 20 * mm, "PREPARED BY:")
    c.drawString(right_x, footer_y + 20 * mm, "NOTED BY:")

    c.line(left_x, footer_y + 10 * mm, left_x + block_w, footer_y + 10 * mm)
    c.line(right_x, footer_y + 10 * mm, right_x + block_w, footer_y + 10 * mm)

    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(left_x + block_w / 2, footer_y + 4 * mm, (employee.get("full_name") or "").strip() or "Employee Name")
    c.drawCentredString(right_x + block_w / 2, footer_y + 4 * mm, focal_name)
    c.setFont("Helvetica", 10)
    c.drawCentredString(left_x + block_w / 2, footer_y - 2 * mm, (employee.get("position") or "").strip() or "Position")
    c.drawCentredString(right_x + block_w / 2, footer_y - 2 * mm, focal_position)


def generate_locator_chart_report(employee: dict, rows: list[dict], start_date: str = "", end_date: str = "") -> Path:
    _colors, A4, _landscape, mm, ImageReader, canvas = _reportlab_modules()
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    output_dir.mkdir(exist_ok=True)
    month_label = _locator_month_label(start_date, end_date)

    filename = f"locator_chart_{_safe_filename(employee.get('full_name') or 'employee')}.pdf"
    pdf_path = output_dir / filename
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    _force_canvas_all_caps(c)
    width, height = A4
    _draw_locator_chart_page(c, width, height, mm, ImageReader, employee, rows, month_label)
    _draw_page_number(c, width, mm)
    c.save()
    return pdf_path


def generate_locator_chart_all_report(
    employee_rows: list[dict],
    rows_by_employee: dict[int, list[dict]],
    start_date: str = "",
    end_date: str = "",
) -> Path:
    _colors, A4, _landscape, mm, ImageReader, canvas = _reportlab_modules()
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    output_dir.mkdir(exist_ok=True)
    month_label = _locator_month_label(start_date, end_date)

    pdf_path = output_dir / "locator_chart_all.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    _force_canvas_all_caps(c)
    width, height = A4
    started = False
    for employee in employee_rows:
        emp_id = int(employee["id"])
        rows = rows_by_employee.get(emp_id) or []
        if not rows:
            continue
        if started:
            _draw_page_number(c, width, mm)
            c.showPage()
        _draw_locator_chart_page(c, width, height, mm, ImageReader, employee, rows, month_label)
        started = True
    if not started:
        # produce at least one empty page with template when no assignment exists
        _draw_locator_chart_page(
            c,
            width,
            height,
            mm,
            ImageReader,
            {"full_name": "", "position": ""},
            [],
            month_label,
        )
    _draw_page_number(c, width, mm)
    c.save()
    return pdf_path


def generate_city_service_summary_report(
    rows: list[dict],
    service_types: list[str],
    start_date: str,
    end_date: str,
) -> Path:
    colors, A4, landscape, mm, ImageReader, canvas = _reportlab_modules()
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    output_dir.mkdir(exist_ok=True)
    settings = fetch_settings()
    pdf_path = output_dir / f"city_service_summary_{_output_report_filename_segment(start_date, end_date)}.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=landscape(A4))
    _force_canvas_all_caps(c)
    width, height = landscape(A4)
    _draw_output_summary_page_letterhead(c, width, height, mm, ImageReader, settings, logo_top_mm=5.0, logo_size_mm=22.0)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, height - 33 * mm, "CITY / MUNICIPALITY SERVICE SUMMARY BY SEX AND TOTAL")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, height - 41 * mm, f"DATE FILTER: {_preview_date_filter_line(start_date, end_date)}")

    left = 10 * mm
    right = width - 10 * mm
    table_width = right - left
    city_w = 36 * mm
    total_w = 24 * mm
    service_w = max(18 * mm, (table_width - city_w - total_w) / max(1, len(service_types)))
    col_widths = [city_w] + [service_w] * len(service_types) + [total_w]
    headers = ["CITY"] + service_types + ["GRAND TOTAL"]
    row_h = 8 * mm
    header_h = 12 * mm
    y_top = height - 56 * mm
    min_y = 20 * mm

    def draw_header(y_header: float) -> None:
        x = left
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        for w_cell in col_widths:
            c.rect(x, y_header, w_cell, header_h, stroke=1, fill=0)
            x += w_cell
        x = left
        for title, w_cell in zip(headers, col_widths):
            _draw_wrapped_centered_header_cell(c, x, y_header, w_cell, header_h, title, "Helvetica-Bold", 7.5, mm)
            x += w_cell

    draw_header(y_top)
    y = y_top - row_h
    c.setFont("Helvetica", 7)

    for row in rows:
        if y < min_y:
            _draw_page_number(c, width, mm)
            c.showPage()
            _force_canvas_all_caps(c)
            draw_header(height - 22 * mm)
            y = height - 22 * mm - row_h
            c.setFont("Helvetica", 7)

        x = left
        c.rect(x, y, col_widths[0], row_h, stroke=1, fill=0)
        c.drawString(x + 1.2 * mm, y + 2.1 * mm, row.get("city_municipality") or "")
        x += col_widths[0]
        for service in service_types:
            c.rect(x, y, service_w, row_h, stroke=1, fill=0)
            svc = (row.get("services") or {}).get(service) or {}
            c.drawString(x + 1 * mm, y + 2.1 * mm, f"M:{svc.get('male', 0)} F:{svc.get('female', 0)} T:{svc.get('total', 0)}")
            x += service_w
        c.rect(x, y, total_w, row_h, stroke=1, fill=0)
        c.drawString(x + 1 * mm, y + 2.1 * mm, f"M:{row.get('male', 0)} F:{row.get('female', 0)} T:{row.get('total', 0)}")
        y -= row_h

    _draw_page_number(c, width, mm)
    c.save()
    return pdf_path


# The DAR's "Verified as correct by" signatory is fixed for every DAR export
# (Excel and PDF alike), regardless of what is configured in the signatories table.
DAR_VERIFIED_BY_NAME = "LENARD KYLE D. FRANCISCO"
DAR_VERIFIED_BY_POSITION = "Focal Person"


def _dar_logo_paths() -> tuple[Path | None, Path | None]:
    # PSA agency logo goes on the left, the National ID / PhilSys logo on the right
    # (matches the official DAR letterhead layout).
    left = _fixed_logo_path("PSA.png")
    right = _fixed_logo_path("National ID.png")
    return left, right


def _dar_month_label(start_date: str, end_date: str) -> str:
    try:
        if start_date:
            dt = datetime.strptime(start_date, "%Y-%m-%d")
            return dt.strftime("%B %Y")
    except Exception:
        pass
    return start_date or ""


def build_dar_workbook(
    rows: list[dict],
    *,
    start_date: str = "",
    end_date: str = "",
    employee_id: str | None = None,
    employee_name: str | None = None,
):
    """Build the Daily Accomplishment Report workbook, matching the official PSA DAR layout:

    Republic of the Philippines / PHILIPPINE STATISTICS AUTHORITY / Daily Accomplishment Report
    Province / City-Municipality / Month-Year
    Accomplishment Record table: Date | Daily Captured | Cumulative | Remarks (service breakdown)
    Grand total, then Prepared by / Verified as correct by signature blocks.
    """
    import io

    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils.units import pixels_to_EMU, points_to_pixels

    wb = Workbook()
    ws = wb.active
    ws.title = "DAR"

    thin = Side(border_style="thin", color="000000")
    medium = Side(border_style="medium", color="000000")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
    right_align = Alignment(horizontal="right", vertical="center")
    header_fill = PatternFill(start_color="EFEFEF", end_color="EFEFEF", fill_type="solid")

    # ---- Group rows (which are per employee/date) into per-date city totals ----
    grouped: dict[str, dict] = {}
    order: list[str] = []
    province = ""
    city = ""
    for r in rows:
        date_raw = r.get("date")
        if not date_raw:
            continue
        province = province or (r.get("province") or "")
        city = city or (r.get("city_municipality") or "")
        if date_raw not in grouped:
            grouped[date_raw] = {"total": 0, **{s: 0 for s in SERVICE_TYPES}}
            order.append(date_raw)
        bucket = grouped[date_raw]
        bucket["total"] += int(r.get("total", 0) or 0)
        for service in SERVICE_TYPES:
            bucket[service] += int(r.get(service, 0) or 0)

    def _sort_key(d: str):
        try:
            return datetime.strptime(d, "%m/%d/%Y")
        except Exception:
            return datetime.max

    order.sort(key=_sort_key)

    # Only show service categories that actually have data anywhere in the range;
    # fall back to the four core PSA services if the report has no data yet.
    active_services = [s for s in SERVICE_TYPES if any(grouped[d][s] for d in order)]
    if not active_services:
        active_services = [
            "National ID Registration",
            "Issuance of National ID in Paper Form Only",
            "TRN Retrieval",
            "Authentication",
        ]

    # ---- Header block (rows 1-6) ----
    ws.merge_cells("B2:G2")
    header_cell = ws.cell(row=2, column=2)
    header_cell.value = "Republic of the Philippines\nPHILIPPINE STATISTICS AUTHORITY\nDaily Accomplishment Report"
    header_cell.font = Font(name="Arial", size=12, bold=True)
    header_cell.alignment = center
    for c in range(2, 8):
        cell = ws.cell(row=2, column=c)
        cell.border = Border(
            top=medium, bottom=thin,
            left=medium if c == 2 else thin,
            right=medium if c == 7 else thin,
        )
    ws.row_dimensions[2].height = 60

    left_logo, right_logo = _dar_logo_paths()

    def _place_logo(path: Path, col: int):
        try:
            img = XLImage(str(path))
            size = 52
            img.width = size
            img.height = size
            anchor = OneCellAnchor()
            anchor._from.col = col - 1
            anchor._from.row = 1
            anchor._from.colOff = pixels_to_EMU(4)
            anchor._from.rowOff = pixels_to_EMU(max(0, (points_to_pixels(60) - size) / 2))
            anchor.ext.width = pixels_to_EMU(size)
            anchor.ext.height = pixels_to_EMU(size)
            img.anchor = anchor
            ws.add_image(img)
        except Exception:
            pass

    if left_logo and left_logo.exists():
        _place_logo(left_logo, 2)
    if right_logo and right_logo.exists():
        _place_logo(right_logo, 7)

    def _meta_row(row: int, label: str, value: str):
        # NOTE: when cells are merged, Excel draws the outer edge of the
        # merged block from whichever underlying cell sits on that edge --
        # not just the top-left "anchor" cell. Applying the border to only
        # the anchor cell (as before) left the rightmost cell of the B:C and
        # D:G merges with no border definition at all, which is what caused
        # the missing/broken right-hand border on column G for rows 3-5.
        # Fix: apply the border to every cell in each merged range.
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        for c in (2, 3):
            cell = ws.cell(row=row, column=c)
            if c == 2:
                cell.value = label
                cell.font = Font(name="Arial", size=11)
                cell.alignment = Alignment(horizontal="left", vertical="center")
            cell.border = Border(
                left=medium if c == 2 else thin,
                right=thin,
                top=thin,
                bottom=thin,
            )

        ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=7)
        for c in (4, 5, 6, 7):
            cell = ws.cell(row=row, column=c)
            if c == 4:
                cell.value = value
                cell.font = Font(name="Arial", size=11, bold=True, italic=True)
                cell.alignment = Alignment(horizontal="left", vertical="center")
            cell.border = Border(
                left=thin,
                right=medium if c == 7 else thin,
                top=thin,
                bottom=thin,
            )

    _meta_row(3, "Province:", province or "")
    _meta_row(4, "City/Municipality:", city or (employee_name and "") or "")
    _meta_row(5, "Month/Year:", _dar_month_label(start_date, end_date))

    ws.merge_cells("B6:G6")
    rec_cell = ws.cell(row=6, column=2)
    rec_cell.value = "Accomplishment Record"
    rec_cell.font = Font(name="Arial", size=11, bold=True)
    rec_cell.alignment = center
    for c in range(2, 8):
        ws.cell(row=6, column=c).border = Border(
            top=thin, bottom=thin,
            left=medium if c == 2 else thin,
            right=medium if c == 7 else thin,
        )

    # ---- Table header (rows 7-8) ----
    ws.cell(row=7, column=2, value="Date")
    ws.cell(row=8, column=2, value="(mm/dd)")
    ws.merge_cells(start_row=7, start_column=3, end_row=7, end_column=4)
    ws.cell(row=7, column=3, value="No. of Captured")
    ws.cell(row=8, column=3, value="Daily Captured")
    ws.cell(row=8, column=4, value="Cumulative")
    ws.merge_cells(start_row=7, start_column=5, end_row=8, end_column=7)
    ws.cell(row=7, column=5, value="Remarks")

    for r in (7, 8):
        ws.row_dimensions[r].height = 20
        for c in range(2, 8):
            cell = ws.cell(row=r, column=c)
            if cell.value is not None:
                cell.font = Font(name="Arial", size=11, bold=True)
                cell.alignment = center
            cell.border = Border(
                top=thin,
                bottom=medium if r == 8 else thin,
                left=medium if c == 2 else thin,
                right=medium if c == 7 else thin,
            )

    # ---- Data rows (Legend row removed per updated layout) ----
    current_row = 9
    cumulative = 0
    block_start_rows: list[int] = []
    for date_raw in order:
        bucket = grouped[date_raw]
        block_start = current_row
        block_start_rows.append(block_start)
        try:
            date_val = datetime.strptime(date_raw, "%m/%d/%Y").date()
        except Exception:
            date_val = None

        daily_total = bucket["total"]
        cumulative += daily_total

        n_service_rows = len(active_services)
        # Date/Daily Captured/Cumulative sit on the block's first row; the service
        # breakdown starts on the row right below it, matching the reference DAR layout.
        total_row = block_start + 1 + n_service_rows
        block_end = total_row + 1  # + 1 spacer row

        ws.merge_cells(start_row=block_start, start_column=2, end_row=block_end, end_column=2)
        ws.merge_cells(start_row=block_start, start_column=3, end_row=block_end, end_column=3)
        ws.merge_cells(start_row=block_start, start_column=4, end_row=block_end, end_column=4)

        date_cell = ws.cell(row=block_start, column=2)
        date_cell.value = date_val or date_raw
        if date_val:
            date_cell.number_format = "mm/dd"
        date_cell.font = Font(name="Arial", size=10)
        date_cell.alignment = center

        cap_cell = ws.cell(row=block_start, column=3)
        cap_cell.value = daily_total
        cap_cell.font = Font(name="Arial", size=10)
        cap_cell.alignment = center

        cum_cell = ws.cell(row=block_start, column=4)
        cum_cell.value = cumulative
        cum_cell.font = Font(name="Arial", size=10)
        cum_cell.alignment = center

        for idx, service in enumerate(active_services):
            r = block_start + 1 + idx
            label_cell = ws.cell(row=r, column=5)
            label_cell.value = service
            label_cell.font = Font(name="Arial", size=10)
            label_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            val = bucket.get(service, 0)
            val_cell = ws.cell(row=r, column=6)
            if val:
                val_cell.value = val
            val_cell.font = Font(name="Arial", size=10)
            val_cell.alignment = Alignment(horizontal="center", vertical="center")

        total_label = ws.cell(row=total_row, column=5)
        total_label.value = "Total"
        total_label.font = Font(name="Arial", size=10, bold=True, italic=True)
        total_label.alignment = Alignment(horizontal="right", vertical="center")
        total_val = ws.cell(row=total_row, column=6)
        total_val.value = daily_total
        total_val.font = Font(name="Arial", size=10, bold=True)
        total_val.alignment = Alignment(horizontal="center", vertical="center")

        # ---- Borders for the whole block: thin grid everywhere, with the medium
        # exterior box kept only on the left/right edges of the printed table. ----
        for r in range(block_start, block_end + 1):
            ws.row_dimensions[r].height = 24
            for c in range(2, 8):
                cell = ws.cell(row=r, column=c)
                cell.border = Border(
                    left=medium if c == 2 else thin,
                    right=medium if c == 7 else thin,
                    top=thin,
                    bottom=thin,
                )

        current_row = block_end + 1

    if not order:
        # No data yet: still render an empty table row so the template prints cleanly.
        # Merge B/C/D (Date, Daily Captured, Cumulative) and E:F (Remarks label) so the
        # empty block has exactly the same cell structure/borders as a populated block.
        ws.merge_cells(start_row=9, start_column=2, end_row=10, end_column=2)
        ws.merge_cells(start_row=9, start_column=3, end_row=10, end_column=3)
        ws.merge_cells(start_row=9, start_column=4, end_row=10, end_column=4)
        for r in (9, 10):
            ws.row_dimensions[r].height = 24
            for c in range(2, 8):
                ws.cell(row=r, column=c).border = Border(
                    left=medium if c == 2 else thin,
                    right=medium if c == 7 else thin,
                    top=thin,
                    bottom=thin,
                )
        current_row = 11

    # ---- Grand total ----
    grand_total_row = current_row
    label_cell = ws.cell(row=grand_total_row, column=2)
    label_cell.value = "Total"
    label_cell.font = Font(name="Arial", size=11, bold=True)
    label_cell.alignment = Alignment(horizontal="right", vertical="center")
    value_cell = ws.cell(row=grand_total_row, column=4)
    value_cell.value = cumulative
    value_cell.font = Font(name="Arial", size=10)
    value_cell.alignment = center
    for c in range(2, 8):
        cell = ws.cell(row=grand_total_row, column=c)
        cell.border = Border(
            left=medium if c == 2 else thin,
            right=medium if c == 7 else thin,
            top=thin,
            bottom=medium,
        )

    # ---- Signatories ----
    sigs = signatories_for_report("output")
    prepared = (sigs or {}).get("prepared_by") or {}
    verified = (sigs or {}).get("verified_by") or {}

    prepared_by_name = employee_name or prepared.get("name") or ""
    prepared_by_position = prepared.get("position") or "Registration Kit Operator"
    if employee_id and not employee_name:
        emp = get_employee(int(employee_id)) if str(employee_id).isdigit() else None
        if emp:
            prepared_by_name = emp["full_name"] or prepared_by_name
            prepared_by_position = emp["position"] or prepared_by_position

    # The DAR's "Verified as correct by" signatory is fixed and does not come from the
    # configurable signatories table.
    verified_by_name = DAR_VERIFIED_BY_NAME
    verified_by_position = DAR_VERIFIED_BY_POSITION

    label_row = grand_total_row + 2
    ws.cell(row=label_row, column=2, value="Prepared by:").font = Font(name="Arial", size=10)
    ws.cell(row=label_row, column=2).alignment = Alignment(horizontal="right", vertical="center")
    ws.cell(row=label_row, column=5, value="Verified as correct by:").font = Font(name="Arial", size=10)
    ws.cell(row=label_row, column=5).alignment = Alignment(horizontal="left", vertical="center")

    name_row = label_row + 1
    ws.merge_cells(start_row=name_row, start_column=2, end_row=name_row, end_column=4)
    ws.merge_cells(start_row=name_row, start_column=5, end_row=name_row, end_column=7)
    ncell1 = ws.cell(row=name_row, column=2, value=(prepared_by_name or "").upper())
    ncell1.font = Font(name="Arial", size=10, bold=True)
    ncell1.alignment = center
    ncell2 = ws.cell(row=name_row, column=5, value=(verified_by_name or "").upper())
    ncell2.font = Font(name="Arial", size=10, bold=True)
    ncell2.alignment = center

    pos_row = name_row + 1
    ws.merge_cells(start_row=pos_row, start_column=2, end_row=pos_row, end_column=4)
    ws.merge_cells(start_row=pos_row, start_column=5, end_row=pos_row, end_column=7)
    pcell1 = ws.cell(row=pos_row, column=2, value=prepared_by_position)
    pcell1.font = Font(name="Arial", size=9)
    pcell1.alignment = center
    pcell2 = ws.cell(row=pos_row, column=5, value=verified_by_position)
    pcell2.font = Font(name="Arial", size=9)
    pcell2.alignment = center

    # ---- Column widths / page setup ----
    ws.column_dimensions["A"].width = 3.7
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 32
    ws.column_dimensions["F"].width = 9
    ws.column_dimensions["G"].width = 7

    ws.sheet_view.showGridLines = False
    ws.print_area = f"B1:G{pos_row + 2}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_margins.left = 0.3
    ws.page_margins.right = 0.3
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5

    # Repeat the letterhead/logo + table header + legend (rows 1-9) on every printed page,
    # so a report spanning multiple pages doesn't show a headerless, borderless continuation.
    ws.print_title_rows = "1:8"

    # Avoid splitting a single date's block (its merged Date/Cumulative cells and service
    # rows) across a page break, which is what produces the broken/half-drawn borders when
    # a report runs past one page. We estimate how many data rows fit under the repeating
    # header and insert a manual page break just before whichever block would otherwise
    # overflow onto the next page.
    if block_start_rows:
        from openpyxl.worksheet.pagebreak import Break

        block_height = len(active_services) + 3  # date row + service rows + total row + spacer
        header_pt = 60 + 4 * 15 + 2 * 20  # row2 + rows3-6 + header rows7-8 (no legend row anymore)
        margins_pt = (0.5 + 0.5) * 72
        usable_pt = (297 / 25.4) * 72 - margins_pt - header_pt  # A4 portrait content height
        rows_per_page = max(6, int(usable_pt // 24))

        rows_since_break = 0
        prev_block_start = None
        for bs in block_start_rows:
            if rows_since_break + block_height > rows_per_page and prev_block_start is not None:
                ws.row_breaks.append(Break(id=bs - 1))
                rows_since_break = 0
            rows_since_break += block_height
            prev_block_start = bs

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def _draw_dar_pdf_page(c, width, height, mm, ImageReader, colors, rows_for_scope, *, province, city, month_label, employee_name, employee_position):
    """Draw a single DAR page (one employee/scope), matching the Excel DAR layout exactly:
    a single medium-weight outer box, a thin grid inside it, no shaded fills, and no
    Legend row -- Date | Daily Captured | Cumulative | Remarks (service label + count).
    """
    THIN = 0.5
    MEDIUM = 1.1

    left = 14 * mm
    right = width - 14 * mm
    top = height - 12 * mm

    left_logo, right_logo = _dar_logo_paths()
    logo_size = 16 * mm
    if left_logo and left_logo.exists():
        try:
            c.drawImage(ImageReader(str(left_logo)), left, top - logo_size, logo_size, logo_size, mask="auto")
        except Exception:
            pass
    if right_logo and right_logo.exists():
        try:
            c.drawImage(ImageReader(str(right_logo)), right - logo_size, top - logo_size, logo_size, logo_size, mask="auto")
        except Exception:
            pass

    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, top - 5 * mm, "Republic of the Philippines")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, top - 10 * mm, "PHILIPPINE STATISTICS AUTHORITY")
    c.drawCentredString(width / 2, top - 15 * mm, "Daily Accomplishment Report")

    meta_y = top - logo_size - 4 * mm
    c.setFont("Helvetica", 9)
    c.drawString(left, meta_y, f"Province: {province or ''}")
    c.drawString(left, meta_y - 5 * mm, f"City/Municipality: {city or ''}")
    c.drawString(left, meta_y - 10 * mm, f"Month/Year: {month_label or ''}")
    if employee_name:
        c.drawString(left, meta_y - 15 * mm, f"Employee: {employee_name}" + (f" ({employee_position})" if employee_position else ""))

    # ---- Group rows by date ----
    grouped: dict[str, dict] = {}
    order: list[str] = []
    for r in rows_for_scope:
        date_raw = r.get("date")
        if not date_raw:
            continue
        if date_raw not in grouped:
            grouped[date_raw] = {"total": 0, **{s: 0 for s in SERVICE_TYPES}}
            order.append(date_raw)
        bucket = grouped[date_raw]
        bucket["total"] += int(r.get("total", 0) or 0)
        for service in SERVICE_TYPES:
            bucket[service] += int(r.get(service, 0) or 0)

    def _sort_key(d: str):
        try:
            return datetime.strptime(d, "%m/%d/%Y")
        except Exception:
            return datetime.max

    order.sort(key=_sort_key)

    active_services = [s for s in SERVICE_TYPES if any(grouped[d][s] for d in order)] or [
        "National ID Registration",
        "Issuance of National ID in Paper Form Only",
        "TRN Retrieval",
        "Authentication",
    ]

    date_w = 20 * mm
    cap_w = 22 * mm
    cum_w = 22 * mm
    value_w = 16 * mm
    label_w = (right - left) - date_w - cap_w - cum_w - value_w
    col_x = [left, left + date_w, left + date_w + cap_w, left + date_w + cap_w + cum_w,
             left + date_w + cap_w + cum_w + label_w, right]

    header_h1 = 6 * mm
    header_h2 = 7 * mm
    header_h = header_h1 + header_h2
    row_h = 6.2 * mm  # height of a single Date/service/Total line
    min_y = 45 * mm

    def _line(x0, y0, x1, y1, weight):
        c.setLineWidth(weight)
        c.line(x0, y0, x1, y1)

    def draw_table_header(y_top):
        """Draws the two-row Date/No. of Captured/Remarks header and returns (y_after, page_top_y)."""
        y1 = y_top - header_h1
        y2 = y_top - header_h

        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString((col_x[0] + col_x[1]) / 2, y2 + header_h / 2 - 1, "Date")
        c.setFont("Helvetica", 6.5)
        c.drawCentredString((col_x[0] + col_x[1]) / 2, y2 + header_h / 2 - 4.5, "(mm/dd)")

        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString((col_x[1] + col_x[3]) / 2, y1 - header_h1 / 2 + 1, "No. of Captured")
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString((col_x[1] + col_x[2]) / 2, y2 + header_h2 / 2 - 1, "Daily")
        c.drawCentredString((col_x[1] + col_x[2]) / 2, y2 + header_h2 / 2 - 4, "Captured")
        c.drawCentredString((col_x[2] + col_x[3]) / 2, y2 + header_h2 / 2 - 2.5, "Cumulative")

        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString((col_x[3] + col_x[5]) / 2, y2 + header_h / 2 - 1, "Remarks")

        # grid lines for the header block
        for x in col_x:
            _line(x, y_top, x, y2, MEDIUM if x in (col_x[0], col_x[5]) else THIN)
        _line(col_x[0], y_top, col_x[5], y_top, MEDIUM)
        _line(col_x[1], y1, col_x[3], y1, THIN)  # split "No. of Captured" from its two sub-columns
        _line(col_x[0], y2, col_x[5], y2, MEDIUM)
        return y2

    def _wrap(text, font, size, max_w):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if c.stringWidth(trial, font, size) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    y = (meta_y - 20 * mm) if employee_name else (meta_y - 15 * mm)
    page_top_of_table = y
    y = draw_table_header(y)

    cumulative = 0

    def _new_page_if_needed(needed_h):
        nonlocal y, page_top_of_table
        if y - needed_h < min_y:
            c.showPage()
            y = top
            page_top_of_table = y - 25 * mm
            y = draw_table_header(page_top_of_table)

    sub_line_h = 3.3 * mm
    label_font = "Helvetica"
    label_size = 7.5

    for date_raw in order:
        bucket = grouped[date_raw]
        cumulative += bucket["total"]

        # Wrap long service labels so they never spill past the Remarks column.
        service_lines = []
        for service in active_services:
            lines = _wrap(service, label_font, label_size, label_w - 3 * mm)
            r_h = max(row_h, len(lines) * sub_line_h)
            service_lines.append((service, lines, bucket.get(service, 0), r_h))

        row_heights = [row_h] + [rh for (_s, _l, _v, rh) in service_lines] + [row_h]
        block_h = sum(row_heights)
        _new_page_if_needed(block_h)

        block_top = y

        # Date / Daily Captured / Cumulative row
        c.setFont("Helvetica", 8)
        c.drawCentredString((col_x[0] + col_x[1]) / 2, y - row_h / 2 - 1.5, str(date_raw))
        c.drawCentredString((col_x[1] + col_x[2]) / 2, y - row_h / 2 - 1.5, str(bucket["total"]))
        c.drawCentredString((col_x[2] + col_x[3]) / 2, y - row_h / 2 - 1.5, str(cumulative))
        y -= row_h

        for service, lines, val, r_h in service_lines:
            c.setFont(label_font, label_size)
            ty = y - (r_h - (len(lines) - 1) * sub_line_h) / 2 + (len(lines) - 1) * sub_line_h - 1.5
            for line in lines:
                c.drawString(col_x[3] + 1.5 * mm, ty, line)
                ty -= sub_line_h
            if val:
                c.drawCentredString((col_x[4] + col_x[5]) / 2, y - r_h / 2 - 1.5, str(val))
            y -= r_h

        # Total row
        c.setFont("Helvetica-BoldOblique", 7.5)
        c.drawRightString(col_x[4] - 1.5 * mm, y - row_h / 2 - 1.5, "Total")
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString((col_x[4] + col_x[5]) / 2, y - row_h / 2 - 1.5, str(bucket["total"]))
        y -= row_h

        block_bottom = y

        # Grid for this block: outer left/right medium, internal horizontals thin,
        # vertical between Date/Captured/Cumulative spans the whole block, Remarks
        # split (label | value) spans the whole block too.
        for x in col_x:
            _line(x, block_top, x, block_bottom, MEDIUM if x in (col_x[0], col_x[5]) else THIN)
        yy = block_top
        for rh in row_heights[:-1]:
            yy -= rh
            _line(col_x[3], yy, col_x[5], yy, THIN)  # only the Remarks columns get row separators
        _line(col_x[0], block_bottom, col_x[5], block_bottom, THIN)

    grand_h = row_h + 1.5 * mm
    _new_page_if_needed(grand_h)
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(col_x[2] - 2 * mm, y - grand_h / 2 - 1.5, "Total")
    c.drawCentredString((col_x[2] + col_x[3]) / 2, y - grand_h / 2 - 1.5, str(cumulative))
    for x in col_x:
        _line(x, y, x, y - grand_h, MEDIUM if x in (col_x[0], col_x[5]) else THIN)
    _line(col_x[0], y - grand_h, col_x[5], y - grand_h, MEDIUM)
    y -= grand_h

    return y


def generate_dar_pdf(rows: list[dict], *, start_date: str = "", end_date: str = "", employee_id: str | None = None, employee_name: str | None = None) -> Path:
    """Build the Daily Accomplishment Report as a PDF (one scope per call), matching the Excel DAR layout."""
    colors_mod, A4, landscape_fn, mm, ImageReader, canvas = _reportlab_modules()
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    output_dir.mkdir(exist_ok=True)

    seg = _output_report_filename_segment(start_date, end_date)
    name_part = f"_{_safe_filename(employee_name)}" if employee_name else "_all"
    pdf_path = output_dir / f"DAR_{seg}{name_part}.pdf"

    province = rows[0].get("province") if rows else ""
    city = rows[0].get("city_municipality") if rows else ""
    month_label = _dar_month_label(start_date, end_date)

    employee_position = None
    if employee_id:
        try:
            emp = get_employee(int(employee_id))
            employee_position = emp["position"] if emp else None
        except (ValueError, TypeError):
            employee_position = None

    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4

    y_after_table = _draw_dar_pdf_page(
        c, width, height, mm, ImageReader, colors_mod, rows,
        province=province, city=city, month_label=month_label,
        employee_name=employee_name, employee_position=employee_position,
    )

    sigs = signatories_for_report("output")
    prepared_position = employee_position or "Registration Kit Operator"
    _draw_signatories(
        c, width, sigs, mm,
        prepared_name=employee_name,
        prepared_position=prepared_position,
        default_prepared_position="Registration Kit Operator",
        default_verified_position=DAR_VERIFIED_BY_POSITION,
        footer_anchor_mm=14.0,
        label_size=8.5,
        position_size=7.5,
        verified_name_override=DAR_VERIFIED_BY_NAME,
        verified_position_override=DAR_VERIFIED_BY_POSITION,
    )
    _draw_page_number(c, width, mm)
    c.save()
    return pdf_path


def generate_all_employees_dar_pdf_zip(start_date: str, end_date: str) -> Path:
    """Generate one DAR PDF per active employee (with output rows in range) and zip them together."""
    output_dir = Path(current_app.config["REPORT_OUTPUT_DIR"])
    output_dir.mkdir(exist_ok=True)
    seg = _output_report_filename_segment(start_date, end_date)
    zip_path = output_dir / f"{seg}_all_employees_DAR.zip"

    with ZipFile(zip_path, "w") as archive:
        for employee in list_employees():
            if not employee["active"]:
                continue
            filters: dict = {"employee_id": employee["id"]}
            if (start_date or "").strip():
                filters["start_date"] = start_date
            if (end_date or "").strip():
                filters["end_date"] = end_date
            rows = output_per_person_rows(filters)
            if not rows:
                continue
            pdf_path = generate_dar_pdf(
                rows,
                start_date=start_date,
                end_date=end_date,
                employee_id=str(employee["id"]),
                employee_name=employee["full_name"],
            )
            archive.write(pdf_path, arcname=pdf_path.name)
            pdf_path.unlink(missing_ok=True)

    return zip_path
