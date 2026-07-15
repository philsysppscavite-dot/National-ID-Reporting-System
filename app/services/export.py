"""Export saved Data Entries into an external Google Sheet ("Send Report
to Google Sheet").

Entries are always created and stored first in the app's own SQLite
database as usual. This module only handles the *export* step: once a
user is ready, it pushes their (not-yet-sent) Data Entry rows into the
target spreadsheet -- e.g. the province's shared "TRN Daily Logsheet"
Google Sheet -- so nothing needs to be retyped there by hand.

Entries are split into a separate worksheet *tab* per Type of
Registration (record_type) -- e.g. a "National ID Registration" tab and
an "Updating" tab -- since the two record types capture very different
fields. A tab is looked up by name (case-insensitive) and created
automatically the first time that record type is sent, so nothing needs
to be pre-configured for it in the target spreadsheet.

The target spreadsheet is configured by an admin (Dashboard -> Report
Settings -> "TRN Logsheet Google Sheet URL", stored as the
`trn_logsheet_url` app setting) rather than hard-coded, since the sheet
name/link can change (e.g. a new sheet each month).

Because that spreadsheet is maintained outside this app (its own header
row, in whatever order/labels its owner set up), this module matches our
Data Entry fields against the *actual* header row it finds by loosely
matching header text (case/spacing/punctuation-insensitive, a handful of
recognized synonyms per field) rather than assuming a fixed column order.
Any header cell that isn't recognized is simply left blank for our rows;
any of our fields that aren't found in the header are appended as new
columns at the end (never inserted in the middle -- see sheets_db.py for
why that matters for a live sheet). A brand-new/blank tab gets a
sensible default header row written for it automatically.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from gspread.utils import rowcol_to_a1

from .. import sheets_db

# Data Entry field -> (default header label, [recognized header synonyms]).
# Order here is also the order used when a brand-new/blank sheet needs a
# header row generated for it.
FIELD_HEADER_MAP: dict[str, tuple[str, list[str]]] = {
    "reporting_date": ("Reporting Date", ["date", "reporting date", "date of report"]),
    "city_municipality": ("City / Municipality", ["city", "municipality", "city/municipality", "city municipality"]),
    "barangay": ("Barangay", ["barangay", "brgy"]),
    "specific_location": ("Specific Location", ["specific location", "venue", "location"]),
    "type_of_rc": ("Type of RC", ["type of rc", "rc type"]),
    "rko_full_name": ("Name of RKO", ["name of rko", "rko", "rko name"]),
    "applicant_first_name": ("First Name", ["first name", "given name"]),
    "applicant_middle_name": ("Middle Name", ["middle name"]),
    "applicant_last_name": ("Last Name", ["last name", "surname"]),
    "applicant_suffix": ("Suffix", ["suffix"]),
    "dob_month": ("DOB Month", ["dob month", "birth month"]),
    "dob_day": ("DOB Day", ["dob day", "birth day"]),
    "dob_year": ("DOB Year", ["dob year", "birth year"]),
    "gender": ("Gender", ["gender", "sex"]),
    "age_category": ("Age Category", ["age category", "age"]),
    "contact_number": ("Contact Number", ["contact number", "mobile number", "contact no"]),
    "overseas_registrant": ("Overseas Registrant", ["overseas registrant", "overseas"]),
    "trn_or_pcn": ("TRN / National ID No.", ["trn", "pcn", "trn or pcn", "national id no", "transaction reference number"]),
    "old_trn": ("Old TRN (Recaptured)", ["old trn", "recaptured"]),
    "service_availed": ("Services Availed", ["services availed", "service availed"]),
    "ephilid_status": ("ePhilID Status", ["ephilid status"]),
    "ephilid_issued_date": ("ePhilID Issued Date", ["ephilid issued date"]),
    "digital_id_assistance": ("Digital ID Assistance", ["digital id assistance", "assistance given"]),
    "digital_id_generated": ("Digital ID Generated", ["digital id generated", "successfully generated"]),
    "digital_id_issue_notes": ("Digital ID Issue Notes", ["digital id issue notes", "issues"]),
    "gov_ayuda_programs": ("Government Ayuda Programs", ["government ayuda programs", "ayuda"]),
    "authenticated_status": ("Authenticated", ["authenticated"]),
    "philid_ephilid_presented": ("PhilID/ePhilID Presented?", ["philid ephilid presented", "philid or ephilid presented"]),
    "change_correction": ("Change/Correction", ["change correction"]),
    "supporting_document": ("Supporting Document", ["supporting document", "supporting documents"]),
    "fields_changed": ("Fields to be Changed or corrected", ["fields to be changed or corrected", "fields changed"]),
    "national_id_form_presented": ("National ID in Paper Form", ["national id in paper form", "form of national id presented"]),
}


class ExportError(RuntimeError):
    """Raised for any problem exporting Data Entries to the target sheet."""


def _normalize_header(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _extract_sheet_id(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or parsed.netloc.lower() != "docs.google.com":
        raise ExportError("The configured TRN Logsheet URL must be a docs.google.com Google Sheets link.")
    if "/spreadsheets/d/" not in url:
        raise ExportError("Could not find a spreadsheet ID in the configured TRN Logsheet URL.")
    return url.split("/spreadsheets/d/")[1].split("/")[0]


def _extract_gid(url: str) -> str | None:
    match = re.search(r"[?#&]gid=(\d+)", url or "")
    return match.group(1) if match else None


def _open_worksheet(sheet_url: str, worksheet_title: str | None = None):
    client = sheets_db.get_authorized_client()
    sheet_id = _extract_sheet_id(sheet_url)
    try:
        spreadsheet = client.open_by_key(sheet_id)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user as a flash message
        raise ExportError(
            "Couldn't open the configured TRN Logsheet. Make sure the sheet is shared "
            "with the app's service account as an Editor, and the URL is correct."
        ) from exc

    if worksheet_title:
        for worksheet in spreadsheet.worksheets():
            if worksheet.title.strip().lower() == worksheet_title.strip().lower():
                return worksheet
        try:
            return spreadsheet.add_worksheet(title=worksheet_title, rows=1000, cols=30)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user as a flash message
            raise ExportError(
                f"Couldn't create a '{worksheet_title}' tab in the configured TRN Logsheet."
            ) from exc

    gid = _extract_gid(sheet_url)
    if gid is not None:
        for worksheet in spreadsheet.worksheets():
            if str(worksheet.id) == gid:
                return worksheet
    return spreadsheet.sheet1


def _build_header_index(worksheet) -> tuple[list[str], dict[str, int]]:
    """Returns (header_row, {field_name: 0-based column index})."""
    header_row = worksheet.row_values(1)
    if not header_row:
        header_row = [label for label, _synonyms in FIELD_HEADER_MAP.values()]
        worksheet.update("A1", [header_row], value_input_option="RAW")

    normalized_header = [_normalize_header(cell) for cell in header_row]
    field_to_col: dict[str, int] = {}
    for field, (label, synonyms) in FIELD_HEADER_MAP.items():
        candidates = [_normalize_header(label)] + [_normalize_header(s) for s in synonyms]
        for idx, cell in enumerate(normalized_header):
            if cell in candidates:
                field_to_col[field] = idx
                break

    # Any of our fields not present anywhere in the sheet's header get
    # appended as new columns on the right, so no export data is silently
    # dropped just because this particular sheet doesn't have a matching
    # column yet.
    missing_fields = [f for f in FIELD_HEADER_MAP if f not in field_to_col]
    if missing_fields:
        start_col = len(header_row) + 1
        new_labels = [FIELD_HEADER_MAP[f][0] for f in missing_fields]
        end_col = len(header_row) + len(new_labels)
        cell_range = f"{rowcol_to_a1(1, start_col)}:{rowcol_to_a1(1, end_col)}"
        worksheet.update(cell_range, [new_labels], value_input_option="RAW")
        for offset, field in enumerate(missing_fields):
            field_to_col[field] = len(header_row) + offset
        header_row = header_row + new_labels

    return header_row, field_to_col


def _entry_field_value(entry, field: str) -> str:
    if field == "rko_full_name":
        try:
            return entry["rko_full_name"] or ""
        except (IndexError, KeyError):
            return ""
    try:
        value = entry[field]
    except (IndexError, KeyError):
        return ""
    return "" if value is None else str(value)


def export_data_entries_to_sheet(entries: list, sheet_url: str) -> int:
    """Appends each entry as a new row in the configured Google Sheet,
    split into a separate tab per Type of Registration (record_type) and
    matched to that tab's own header columns. Returns the total number of
    rows written across all tabs. Does not mark anything as sent --
    callers should do that only after this returns successfully."""
    if not sheet_url:
        raise ExportError(
            "No TRN Logsheet URL is configured yet. An administrator can set one "
            "from the Dashboard under Report Settings."
        )
    if not entries:
        return 0

    entries_by_type: dict[str, list] = {}
    for entry in entries:
        record_type = _entry_field_value(entry, "record_type") or "National ID Registration"
        entries_by_type.setdefault(record_type, []).append(entry)

    total_written = 0
    for record_type, group in entries_by_type.items():
        worksheet = _open_worksheet(sheet_url, worksheet_title=record_type)
        header_row, field_to_col = _build_header_index(worksheet)
        width = len(header_row)

        rows = []
        for entry in group:
            row = [""] * width
            for field, col in field_to_col.items():
                row[col] = _entry_field_value(entry, field)
            rows.append(row)

        worksheet.append_rows(rows, value_input_option="RAW")
        total_written += len(rows)

    return total_written
