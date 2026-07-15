from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

from werkzeug.security import generate_password_hash

from . import sheets_db
from .cavite_barangays import BARANGAYS_BY_CITY
from .db import ROLE_ADMIN, ROLE_ISA, ROLE_USER, ROLES, get_db


CITY_MUNICIPALITIES = [
    "ALFONSO",
    "AMADEO",
    "BACOOR CITY",
    "CARMONA",
    "CAVITE CITY",
    "CITY OF DASMARIÑAS",
    "GENERAL EMILIO AGUINALDO",
    "CITY OF GENERAL TRIAS",
    "IMUS CITY",
    "INDANG",
    "KAWIT",
    "MAGALLANES",
    "MARAGONDON",
    "MENDEZ (MENDEZ-NUÑEZ)",
    "NAIC",
    "NOVELETA",
    "ROSARIO",
    "SILANG",
    "TAGAYTAY CITY",
    "TANZA",
    "TERNATE",
    "TRECE MARTIRES CITY (Capital)",
    "GEN. MARIANO ALVAREZ",
]

SERVICE_TYPES = [
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
    "Issuance of National ID in Paper Form and Assistance in Generating the Digital National ID",
    "Recapture and Assistance in Generating the Digital National ID",
]

# --- Data Entry (per-applicant registration log) -----------------------
# A handful of these option lists are placeholders until the definitive
# dropdown values are provided -- those fields are left as free-text
# inputs on the form for now (Barangay, Specific Location, Age Category,
# ePhilID Status, Government Ayuda Programs) so nothing is guessed
# incorrectly. The lists below are the ones already spelled out with
# fixed values -- Type of RC and everything under RECORD_TYPE_UPDATING
# come from the "Classification Guide and Dropdown" sheet of the TRN
# Daily Logsheet.
GENDER_OPTIONS = ["Male", "Female"]

AGE_CATEGORY_OPTIONS = [
    "0-4 years old",
    "5 years old and above",
]

EPHILID_STATUS_OPTIONS = [
    "Not Generated",
    "Issued",
    "Unclickable in DCS",
    "Data Usage Expired",
    "Digital Card Service under maintenance",
    "Not yet issued",
    "RINF",
    "Available for Printing",
]

# A Data Entry is either a National ID Registration transaction or an
# Updating (change/correction) transaction -- which fields apply differs
# between the two, per the logsheet's own "Registration" vs "Updating"
# column groupings.
RECORD_TYPE_REGISTRATION = "National ID Registration"
RECORD_TYPE_UPDATING = "Updating"
RECORD_TYPE_OPTIONS = [RECORD_TYPE_REGISTRATION, RECORD_TYPE_UPDATING]

TYPE_OF_RC_OPTIONS = [
    "PSA-based",
    "Mall-based",
    "LGU-fixed",
    "LGU Mobile",
    "DSWD SWAD/CIU",
    "DSWD Mobile",
    "CRS colocation",
    "DMW colocation",
    "Airport colocation",
    "Seaport colocation",
    "Public Transport Terminal",
    "Caravans",
    "Bagong Pilipinas Serbisyo Fair",
    "NHA People's Caravan",
    "PhilSys on Wheels",
    "DA mobile",
    "NGA mobile",
    "NGA colocation",
    "Institutional Registration",
    "School",
    "Private Colocation",
    "Social Security System",
    "Government Service Insurance System",
    "PhilHealth",
    "Pag-IBIG",
    "Comelec",
    "PHILPost",
    "DSWD FDS",
    "Rehistro Bulilit",
    "Hospital Colocation",
    "PSA Statistical Activities",
    "DOH Retained Hospitals",
    "BSFI Colocation",
    "DOLE TUPAD",
    "Bagong Pilipinas eGovPH Serbisyo Hub",
]

# "Change/Correction" -- what kind of Updating transaction this is.
CHANGE_CORRECTION_OPTIONS = [
    "Change of Demographic information",
    "Correction of Demographic information",
    "TECO",
]

# "Fields to be Changed or corrected"
FIELDS_CHANGED_OPTIONS = [
    "First Name which includes Suffix and/or Middle Name",
    "Last Name",
    "Sex",
    "Date of Birth",
    "Place of Birth",
    "Blood Type",
    "Change of Entry on the item from \"Filipino\" to \"Resident Alien\"",
    "Change of Entry on the item from \"Resident Alien\" to \"Filipino\" Citizen",
    "Permanent/Present Address",
    "Single to Married",
    "Married to Single",
    "Married to Annulled",
    "Married to Divorced",
    "Married to Widowed",
    "Undisclosed to Single",
    "Undisclosed to Married",
    "Undisclosed to Widowed",
    "Undisclosed to Divorced",
    "Widowed to Single",
    "Widowed to Married",
    "Contact Number",
    "Email Address",
    "TECO",
]

# "Supporting Document" -- List of Identification and/or Supporting Documents
SUPPORTING_DOCUMENT_OPTIONS = [
    "Certificate of Live Birth issued by PSA/NSO/LCRO",
    "Report of Birth issued by PSA/PFSP",
    "Certificate of Live Birth of the mother issued by PSA/NSO/LCRO",
    "Report of Birth of the mother issued by PSA/PFSP",
    "Certificate of Live Birth of the parents issued by PSA/NSO/LCRO",
    "Report of Birth of the parents issued by PSA/NSO/LCRO",
    "Certificate of Marriage of the parents issued by PSA/NSO/LCRO",
    "Report of Marriage of the parents issued by PSA/PFSP",
    "Annotated Certificate of Live Birth or Report of Birth issued by PSA (in case of administrative or judicial correction of entry/ies)",
    "Annotated Certificate of Live Birth or Report of Birth issued by PSA (due to RA No. 9255 and legitimation by the subsequent marriage of parents)",
    "Amended Certificate of Live Birth issued by PSA (in case of Adoption pursuant to RA No. 11642) or NSO (Administrative Order No. 1 s. of 1993)",
    "Certificate of Marriage issued by PSA/NSO/LCRO",
    "Report of Marriage issued by PSA/NSO/PFSP",
    "Certificate of Marriage issued Sharia District/Circuit",
    "Annotated Certificate of Marriage or Report of Marriage issued by PSA/NSO",
    "Certificate of Marriage (CEMAR) issued by PSA/NSO",
    "Certificate of No Marriage (CENOMAR) issued by PSA/NSO",
    "Alien Certificate of Recognition or ACR Identity Card",
    "Sworn Certification of the Applicant stating the the aggregated days of stay in the Philippines is more than 180 days.",
    "Valid Foreign Passport",
    "Certificate of Retention or Reacquisition of Filipino Citizenship issued by the Bureau of Immigration (BI) or PFSP (for dual citizenship) pursuant to RA No. 9225",
    "Certificate of Naturalization issued by the Special Committee on Naturalization through administrative naturalization pursuant to RA No. 9139",
    "Certificate of Naturalization issued by the BI through legislative naturalization",
    "Certificate of Naturalization issued by the BI through judicial naturalization pursuant to Commonwealth Act No. 473",
    "Any supporting document showing that the registered person is a Filipino citizen",
    "Blood typing result",
    "Barangay Certificate or Barangay ID stating new address",
    "Proof of billing (at least 3 months) w/ name of the registered person",
    "Certificate of Death of the Spouse issued by PSA/NSO/LCRO",
    "Report of Death of Spouse issued by PSA/NSO/PFSP",
    "Annotated Certificate of Marriage issued by PSA/NSO (in case the absentee spouse is declared presumptively dead)",
    "Any supporting document showing the marital status of the registered person",
    "Any supporting document indicating the correct/updated entry of the permanent/present address",
    "Any identification and/or supporting documents",
    "None",
    "TECO",
]

# "National ID in Paper Form" column on the logsheet -- i.e. Form of
# National ID Presented for the Updating transaction.
NATIONAL_ID_FORM_OPTIONS = [
    "PhilID",
    "National ID in Paper Form",
    "Digital National ID",
]

DIGITAL_ID_ASSISTANCE_OPTIONS = [
    ("1", "1 - Assisted / Provided with Assistance"),
    ("2", "2 - Declined: No Smartphone/Mobile Data"),
    ("3", "3 - Declined: Not interested"),
    ("4", "4 - Declined: Already has a Digital National ID"),
]

YES_NO_OPTIONS = ["Yes", "No"]

OVERSEAS_REGISTRANT_OPTIONS = ["Y", "N"]

AUTHENTICATED_OPTIONS = ["Yes Match", "No Match"]

DOB_MONTH_OPTIONS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _upper_text(value: str | None) -> str:
    return (value or "").strip().upper()


def _title_text(value: str | None) -> str:
    """Best-effort Title Case for names and free-text concern fields --
    capitalizes the first letter of each word (including after hyphens
    and apostrophes, e.g. "mary-jane o'brien" -> "Mary-Jane O'Brien"),
    lowercases the rest, and collapses stray whitespace."""
    text = (value or "").strip()
    if not text:
        return ""

    def cap_word(word: str) -> str:
        parts = re.split(r"([-'])", word)
        return "".join(p if p in ("-", "'") else (p[:1].upper() + p[1:].lower()) for p in parts)

    return " ".join(cap_word(w) for w in text.split())


def fetch_settings() -> dict[str, str]:
    rows = get_db().execute("SELECT key, value FROM app_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_setting(key: str, value: str) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    db.commit()


def list_employees() -> list:
    return get_db().execute(
        """
        SELECT id, employee_code, full_name, position, province, city_municipality, active
        FROM employees
        ORDER BY active DESC, full_name ASC
        """
    ).fetchall()


def get_employee(employee_id: int):
    return get_db().execute(
        """
        SELECT id, employee_code, full_name, position, province, city_municipality, active
        FROM employees WHERE id = ?
        """,
        (employee_id,),
    ).fetchone()


def save_employee(employee_id: int | None, payload: dict) -> None:
    db = get_db()
    fields = (
        (_upper_text(payload.get("employee_code")) or None),
        _upper_text(payload["full_name"]),
        _upper_text(payload.get("position")),
        _upper_text(payload.get("province")),
        _upper_text(payload.get("city_municipality")),
        1 if payload.get("active") else 0,
    )
    if employee_id is None:
        db.execute(
            """
            INSERT INTO employees
            (employee_code, full_name, position, province, city_municipality, active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            fields,
        )
    else:
        db.execute(
            """
            UPDATE employees
            SET employee_code=?, full_name=?, position=?, province=?, city_municipality=?, active=?
            WHERE id=?
            """,
            (*fields, employee_id),
        )
    db.commit()


def delete_employee(employee_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
    db.commit()


def list_schedule_employees(position: str) -> list:
    """Employees filtered by position for schedule assignment dropdowns."""
    return get_db().execute(
        """
        SELECT id, full_name, position
        FROM employees
        WHERE active = 1 AND lower(position) = lower(?)
        ORDER BY full_name ASC
        """,
        (position,),
    ).fetchall()


def list_schedules(filters: dict | None = None) -> list:
    filters = filters or {}
    sql = """
        SELECT
            s.id,
            s.schedule_date,
            s.city_municipality,
            s.assigned_rko_employee_id,
            s.assigned_ra_employee_id,
            s.event_place_activity,
            s.status,
            s.vehicle,
            s.needed_rko_count,
            s.needed_ra_count,
            rko.full_name AS assigned_rko_name,
            ra.full_name AS assigned_ra_name
        FROM schedules s
        LEFT JOIN employees rko ON rko.id = s.assigned_rko_employee_id
        LEFT JOIN employees ra ON ra.id = s.assigned_ra_employee_id
        WHERE 1 = 1
    """
    params: list = []
    if filters.get("start_date"):
        sql += " AND s.schedule_date >= ?"
        params.append(filters["start_date"])
    if filters.get("end_date"):
        sql += " AND s.schedule_date <= ?"
        params.append(filters["end_date"])
    if filters.get("status"):
        sql += " AND lower(s.status) = lower(?)"
        params.append(filters["status"])
    if filters.get("employee_id"):
        sql += """
            AND (
                EXISTS (
                    SELECT 1
                    FROM schedule_assignments sa_filter
                    WHERE sa_filter.schedule_id = s.id AND sa_filter.employee_id = ?
                )
                OR s.assigned_rko_employee_id = ?
                OR s.assigned_ra_employee_id = ?
            )
        """
        params.extend([filters["employee_id"], filters["employee_id"], filters["employee_id"]])
    sql += " ORDER BY s.schedule_date ASC, s.city_municipality ASC, s.id ASC"
    rows = get_db().execute(sql, params).fetchall()
    db = get_db()
    result: list[dict] = []
    for row in rows:
        row_dict = dict(row)
        assignments = db.execute(
            """
            SELECT sa.role, sa.employee_id, e.full_name
            FROM schedule_assignments sa
            JOIN employees e ON e.id = sa.employee_id
            WHERE sa.schedule_id = ?
            ORDER BY e.full_name ASC
            """,
            (row["id"],),
        ).fetchall()
        rko_names = [a["full_name"] for a in assignments if a["role"] == "rko"]
        ra_names = [a["full_name"] for a in assignments if a["role"] == "ra"]
        rko_ids = [a["employee_id"] for a in assignments if a["role"] == "rko"]
        ra_ids = [a["employee_id"] for a in assignments if a["role"] == "ra"]

        if not rko_names and row["assigned_rko_name"]:
            rko_names = [row["assigned_rko_name"]]
        if not ra_names and row["assigned_ra_name"]:
            ra_names = [row["assigned_ra_name"]]
        if not rko_ids and row["assigned_rko_employee_id"]:
            rko_ids = [int(row["assigned_rko_employee_id"])]
        if not ra_ids and row["assigned_ra_employee_id"]:
            ra_ids = [int(row["assigned_ra_employee_id"])]

        row_dict["assigned_rko_names"] = rko_names
        row_dict["assigned_ra_names"] = ra_names
        row_dict["assigned_rko_ids"] = rko_ids
        row_dict["assigned_ra_ids"] = ra_ids
        result.append(row_dict)
    return result


def get_schedule(schedule_id: int):
    row = get_db().execute(
        """
        SELECT id, schedule_date, city_municipality, assigned_rko_employee_id,
               assigned_ra_employee_id, event_place_activity, status, vehicle,
               needed_rko_count, needed_ra_count
        FROM schedules
        WHERE id = ?
        """,
        (schedule_id,),
    ).fetchone()
    if not row:
        return None
    db = get_db()
    row_dict = dict(row)
    assignments = db.execute(
        """
        SELECT role, employee_id
        FROM schedule_assignments
        WHERE schedule_id = ?
        """,
        (schedule_id,),
    ).fetchall()
    rko_ids = [a["employee_id"] for a in assignments if a["role"] == "rko"]
    ra_ids = [a["employee_id"] for a in assignments if a["role"] == "ra"]
    if not rko_ids and row["assigned_rko_employee_id"]:
        rko_ids = [int(row["assigned_rko_employee_id"])]
    if not ra_ids and row["assigned_ra_employee_id"]:
        ra_ids = [int(row["assigned_ra_employee_id"])]
    row_dict["assigned_rko_employee_ids"] = rko_ids
    row_dict["assigned_ra_employee_ids"] = ra_ids
    return row_dict


def save_schedule(schedule_id: int | None, payload) -> None:
    db = get_db()
    rko_ids = [
        int(v)
        for v in payload.getlist("assigned_rko_employee_ids")
        if str(v).strip()
    ]
    ra_ids = [
        int(v)
        for v in payload.getlist("assigned_ra_employee_ids")
        if str(v).strip()
    ]
    needed_rko_count = max(0, int(payload.get("needed_rko_count", 1) or 0))
    needed_ra_count = max(0, int(payload.get("needed_ra_count", 1) or 0))
    fields = (
        payload["schedule_date"],
        _upper_text(payload.get("city_municipality")),
        (rko_ids[0] if rko_ids else None),
        (ra_ids[0] if ra_ids else None),
        _upper_text(payload.get("event_place_activity")),
        (_upper_text(payload.get("status", "Pending")) or "PENDING"),
        (_upper_text(payload.get("vehicle", "PSA")) or "PSA"),
        needed_rko_count,
        needed_ra_count,
    )
    if schedule_id is None:
        cursor = db.execute(
            """
            INSERT INTO schedules
            (schedule_date, city_municipality, assigned_rko_employee_id, assigned_ra_employee_id,
             event_place_activity, status, vehicle, needed_rko_count, needed_ra_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fields,
        )
        target_schedule_id = cursor.lastrowid
    else:
        db.execute(
            """
            UPDATE schedules
            SET schedule_date=?, city_municipality=?, assigned_rko_employee_id=?, assigned_ra_employee_id=?,
                event_place_activity=?, status=?, vehicle=?, needed_rko_count=?, needed_ra_count=?
            WHERE id=?
            """,
            (*fields, schedule_id),
        )
        target_schedule_id = schedule_id

    db.execute("DELETE FROM schedule_assignments WHERE schedule_id = ?", (target_schedule_id,))
    for employee_id in sorted(set(rko_ids)):
        db.execute(
            """
            INSERT OR IGNORE INTO schedule_assignments (schedule_id, employee_id, role)
            VALUES (?, ?, 'rko')
            """,
            (target_schedule_id, employee_id),
        )
    for employee_id in sorted(set(ra_ids)):
        db.execute(
            """
            INSERT OR IGNORE INTO schedule_assignments (schedule_id, employee_id, role)
            VALUES (?, ?, 'ra')
            """,
            (target_schedule_id, employee_id),
        )
    db.commit()


def delete_schedule(schedule_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    db.commit()


def list_outputs(filters: dict | None = None) -> list:
    filters = filters or {}
    sql = """
        SELECT o.id, o.work_date, o.category, o.activity_type, o.quantity, o.remarks,
               o.province, o.city_municipality, o.source_ref,
               e.id AS employee_id, e.full_name, e.employee_code
        FROM employee_outputs o
        JOIN employees e ON e.id = o.employee_id
        WHERE 1 = 1
    """
    params: list = []
    if filters.get("employee_id"):
        sql += " AND e.id = ?"
        params.append(filters["employee_id"])
    if filters.get("month"):
        sql += " AND substr(o.work_date, 1, 7) = ?"
        params.append(filters["month"])
    if filters.get("start_date"):
        sql += " AND o.work_date >= ?"
        params.append(filters["start_date"])
    if filters.get("end_date"):
        sql += " AND o.work_date <= ?"
        params.append(filters["end_date"])
    if filters.get("category"):
        sql += " AND lower(o.category) = lower(?)"
        params.append(filters["category"])
    sql += " ORDER BY o.work_date DESC, e.full_name ASC, o.id DESC"
    return get_db().execute(sql, params).fetchall()


def list_import_sources() -> list:
    """All saved import links, newest first, with a live count of how many
    output rows currently in the system are tied to each one (so unchecking
    a source and seeing its "rows counted" drop to 0 is immediately
    verifiable, independent of the historical `rows_imported` tally)."""
    return get_db().execute(
        """
        SELECT s.id, s.source_type, s.original_url, s.normalized_url, s.method,
               s.payload, s.last_check_at, s.last_status, s.last_error,
               s.rows_imported, s.is_active, s.label, s.created_by_name,
               s.created_at,
               (SELECT COUNT(*) FROM employee_outputs o
                 WHERE o.source_ref = s.normalized_url) AS rows_counted
        FROM import_sources s
        ORDER BY s.created_at DESC
        """
    ).fetchall()


def find_import_source(source_type: str, normalized_url: str):
    return get_db().execute(
        "SELECT * FROM import_sources WHERE source_type = ? AND normalized_url = ?",
        (source_type, normalized_url),
    ).fetchone()


def get_import_source(source_id: int):
    return get_db().execute(
        "SELECT * FROM import_sources WHERE id = ?",
        (source_id,),
    ).fetchone()


def save_import_source(
    source_type: str,
    original_url: str,
    normalized_url: str,
    *,
    method: str | None = None,
    payload: str | None = None,
    last_status: str | None = None,
    last_error: str | None = None,
    rows_imported: int | None = None,
    label: str | None = None,
    created_by_user_id: int | None = None,
    created_by_name: str | None = None,
) -> int:
    db = get_db()
    now = datetime.now().isoformat()
    existing = find_import_source(source_type, normalized_url)
    if existing:
        db.execute(
            """
            UPDATE import_sources
            SET original_url = ?,
                method = ?,
                payload = ?,
                last_check_at = ?,
                last_status = ?,
                last_error = ?,
                rows_imported = COALESCE(?, rows_imported),
                label = COALESCE(?, label)
            WHERE id = ?
            """,
            (
                original_url,
                method,
                payload,
                now,
                last_status,
                last_error,
                rows_imported,
                label,
                existing["id"],
            ),
        )
        db.commit()
        return existing["id"]

    cursor = db.execute(
        """
        INSERT INTO import_sources
        (source_type, original_url, normalized_url, method, payload,
         last_check_at, last_status, last_error, rows_imported, is_active,
         label, created_by_user_id, created_by_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            source_type,
            original_url,
            normalized_url,
            method,
            payload,
            now,
            last_status,
            last_error,
            rows_imported or 0,
            label,
            created_by_user_id,
            created_by_name,
        ),
    )
    db.commit()
    return cursor.lastrowid


def set_import_source_active(source_id: int, is_active: bool):
    """Flip a saved import link on/off. Returns the (now-stale) row as it
    was *before* the change so the caller can act on its normalized_url /
    source_type / method / payload -- e.g. to delete or re-pull its rows."""
    source = get_import_source(source_id)
    if not source:
        return None
    db = get_db()
    db.execute(
        "UPDATE import_sources SET is_active = ? WHERE id = ?",
        (1 if is_active else 0, source_id),
    )
    db.commit()
    return source


def delete_import_source(source_id: int) -> bool:
    source = get_import_source(source_id)
    if not source:
        return False
    db = get_db()
    db.execute("DELETE FROM import_sources WHERE id = ?", (source_id,))
    db.commit()
    return True


def count_outputs_by_source_ref(source_ref: str) -> int:
    row = get_db().execute(
        "SELECT COUNT(*) AS c FROM employee_outputs WHERE source_ref = ?",
        (source_ref,),
    ).fetchone()
    return row["c"] if row else 0


def delete_outputs_by_source_ref(source_ref: str) -> int:
    """Remove every output row tied to a specific saved link (used when an
    admin unchecks/deactivates it, so it immediately stops counting
    anywhere in the system -- totals, reports, city records, etc all read
    from this same employee_outputs table)."""
    db = get_db()
    cursor = db.execute(
        "DELETE FROM employee_outputs WHERE source_ref = ?",
        (source_ref,),
    )
    db.commit()
    return cursor.rowcount


def employee_output_totals(filters: dict | None = None) -> list[dict]:
    """Aggregate output quantities by employee only (totaled across all dates)."""
    filters = filters or {}
    sql = """
        SELECT
            e.id,
            e.full_name
    """
    for idx, service in enumerate(SERVICE_TYPES):
        sql += f""",
            SUM(CASE WHEN o.activity_type = ? THEN o.quantity ELSE 0 END) AS s{idx}
        """
    sql += """,
            SUM(o.quantity) AS total
        FROM employee_outputs o
        JOIN employees e ON e.id = o.employee_id
        WHERE 1 = 1
    """

    params: list = list(SERVICE_TYPES)
    if filters.get("employee_id"):
        sql += " AND e.id = ?"
        params.append(filters["employee_id"])
    if filters.get("start_date"):
        sql += " AND o.work_date >= ?"
        params.append(filters["start_date"])
    if filters.get("end_date"):
        sql += " AND o.work_date <= ?"
        params.append(filters["end_date"])

    sql += """
        GROUP BY e.id, e.full_name
        ORDER BY e.full_name ASC
    """

    rows = get_db().execute(sql, params).fetchall()
    result = []
    for row in rows:
        item = {
            "employee_id": row["id"],
            "name": row["full_name"],
            "total": row["total"],
        }
        for idx, service in enumerate(SERVICE_TYPES):
            item[service] = row[f"s{idx}"]
        result.append(item)
    return result


def output_per_person_rows(filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    sql = """
        SELECT
            o.work_date,
            e.full_name,
            COALESCE(NULLIF(o.province, ''), NULLIF(e.province, ''), '') AS province,
            COALESCE(NULLIF(o.city_municipality, ''), NULLIF(e.city_municipality, ''), '') AS city_municipality
    """
    for idx, service in enumerate(SERVICE_TYPES):
        sql += f""",
            SUM(CASE WHEN o.activity_type = ? THEN o.quantity ELSE 0 END) AS s{idx}
        """
    sql += """
            ,SUM(o.quantity) AS total
        FROM employee_outputs o
        JOIN employees e ON e.id = o.employee_id
        WHERE 1 = 1
    """

    params: list = list(SERVICE_TYPES)
    if filters.get("employee_id"):
        sql += " AND e.id = ?"
        params.append(filters["employee_id"])
    if filters.get("start_date"):
        sql += " AND o.work_date >= ?"
        params.append(filters["start_date"])
    if filters.get("end_date"):
        sql += " AND o.work_date <= ?"
        params.append(filters["end_date"])
    if filters.get("city_municipality"):
        sql += " AND COALESCE(NULLIF(o.city_municipality, ''), NULLIF(e.city_municipality, '')) = ?"
        params.append(filters["city_municipality"])

    sql += """
        GROUP BY o.work_date, e.full_name, 3, 4
        ORDER BY e.full_name ASC, o.work_date ASC
    """

    rows = get_db().execute(sql, params).fetchall()
    result = []
    running_totals: dict[str, int] = {}
    for row in rows:
        name = row["full_name"]
        total = row["total"] or 0
        running_totals[name] = running_totals.get(name, 0) + total
        item = {
            "date": datetime.strptime(row["work_date"], "%Y-%m-%d").strftime("%m/%d/%Y"),
            "name": name,
            "province": row["province"],
            "city_municipality": row["city_municipality"],
            "total": total,
            "cumulative": running_totals[name],
        }
        for idx, service in enumerate(SERVICE_TYPES):
            item[service] = row[f"s{idx}"]
        result.append(item)
    result.sort(key=lambda item: (datetime.strptime(item["date"], "%m/%d/%Y"), item["name"]))
    return result


def output_summary_grand_totals(rows: list[dict], service_types: list[str]) -> dict[str, int | dict[str, int]]:
    """Sum each numeric column across filtered rows (date range / employee scope of ``rows``)."""
    by_service: dict[str, int] = {s: 0 for s in service_types}
    total_sum = 0
    cumulative_sum = 0
    for row in rows:
        for s in service_types:
            by_service[s] += int(row.get(s, 0) or 0)
        total_sum += int(row.get("total", 0) or 0)
        cumulative_sum += int(row.get("cumulative", 0) or 0)
    return {"services": by_service, "total": total_sum, "cumulative": cumulative_sum}


def get_output(output_id: int):
    return get_db().execute(
        """
        SELECT id, employee_id, work_date, category, activity_type, quantity, remarks,
               sex, province, city_municipality, source_ref
        FROM employee_outputs WHERE id = ?
        """,
        (output_id,),
    ).fetchone()


def save_output(output_id: int | None, payload: dict) -> None:
    db = get_db()
    fields = (
        int(payload["employee_id"]),
        payload["work_date"],
        _upper_text(payload["category"]),
        payload.get("activity_type", "").strip(),
        _upper_text(payload.get("sex")),
        int(payload.get("quantity", 0) or 0),
        _upper_text(payload.get("remarks")),
        _upper_text(payload.get("province")),
        _upper_text(payload.get("city_municipality")),
        payload.get("source_ref", "").strip(),
        (payload.get("source_key") or "").strip() or None,
    )
    if output_id is None:
        db.execute(
            """
            INSERT OR IGNORE INTO employee_outputs
            (employee_id, work_date, category, activity_type, sex, quantity, remarks,
             province, city_municipality, source_ref, source_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fields,
        )
    else:
        db.execute(
            """
            UPDATE employee_outputs
            SET employee_id=?, work_date=?, category=?, activity_type=?, sex=?, quantity=?, remarks=?,
                province=?, city_municipality=?, source_ref=?, source_key=?
            WHERE id=?
            """,
            (*fields, output_id),
        )
    db.commit()


def delete_output(output_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM employee_outputs WHERE id = ?", (output_id,))
    db.commit()


def list_data_entries(filters: dict | None = None) -> list:
    filters = filters or {}
    sql = """
        SELECT d.*, e.full_name AS rko_full_name
        FROM data_entries d
        LEFT JOIN employees e ON e.id = d.rko_employee_id
        WHERE 1 = 1
    """
    params: list = []
    if filters.get("city_municipality"):
        sql += " AND d.city_municipality = ?"
        params.append(filters["city_municipality"])
    if filters.get("rko_employee_id"):
        sql += " AND d.rko_employee_id = ?"
        params.append(filters["rko_employee_id"])
    if filters.get("record_type"):
        sql += " AND d.record_type = ?"
        params.append(filters["record_type"])
    if filters.get("start_date"):
        sql += " AND d.reporting_date >= ?"
        params.append(filters["start_date"])
    if filters.get("end_date"):
        sql += " AND d.reporting_date <= ?"
        params.append(filters["end_date"])
    if filters.get("search"):
        sql += """ AND (
            d.applicant_first_name LIKE ? OR d.applicant_last_name LIKE ?
            OR d.trn_or_pcn LIKE ?
        )"""
        term = f"%{filters['search']}%"
        params.extend([term, term, term])
    if filters.get("created_by_user_id"):
        sql += " AND d.created_by_user_id = ?"
        params.append(filters["created_by_user_id"])
    if "sent_to_sheet" in filters:
        sql += " AND d.sent_to_sheet = ?"
        params.append(1 if filters["sent_to_sheet"] else 0)
    sql += " ORDER BY d.reporting_date DESC, d.id DESC"
    return get_db().execute(sql, params).fetchall()


def get_data_entry(entry_id: int):
    return get_db().execute(
        "SELECT * FROM data_entries WHERE id = ?",
        (entry_id,),
    ).fetchone()


def save_data_entry(
    entry_id: int | None,
    payload: dict,
    *,
    created_by_user_id: int | None = None,
    created_by_name: str | None = None,
) -> int:
    reporting_date = (payload.get("reporting_date") or "").strip()
    if not reporting_date:
        raise ValueError("Reporting Date is required.")

    old_trn = (payload.get("old_trn") or "").strip()
    if old_trn and not is_valid_trn_ref_no(old_trn):
        raise ValueError("Old TRN (Recaptured Applicants) must be exactly 29 digits.")

    contact_number = (payload.get("contact_number") or "").strip()
    normalized_contact = contact_number
    if contact_number:
        normalized = normalize_mobile_number(contact_number)
        if normalized:
            normalized_contact = normalized

    rko_employee_id = payload.get("rko_employee_id") or None

    record_type = (payload.get("record_type") or "").strip() or RECORD_TYPE_REGISTRATION
    if record_type not in RECORD_TYPE_OPTIONS:
        raise ValueError("Type of Registration must be Registration or Updating.")

    fields = (
        reporting_date,
        _upper_text(payload.get("city_municipality")),
        _upper_text(payload.get("barangay")),
        _title_text(payload.get("specific_location")),
        (payload.get("type_of_rc") or "").strip(),
        int(rko_employee_id) if rko_employee_id else None,
        _title_text(payload.get("applicant_first_name")),
        _title_text(payload.get("applicant_middle_name")),
        _title_text(payload.get("applicant_last_name")),
        _title_text(payload.get("applicant_suffix")),
        (payload.get("trn_or_pcn") or "").strip(),
        (payload.get("age_category") or "").strip(),
        (payload.get("service_availed") or "").strip(),
        (payload.get("ephilid_status") or "").strip(),
        (payload.get("ephilid_issued_date") or "").strip() or None,
        (payload.get("digital_id_assistance") or "").strip(),
        (payload.get("digital_id_generated") or "").strip(),
        (payload.get("digital_id_issue_notes") or "").strip(),
        (payload.get("dob_month") or "").strip(),
        (payload.get("dob_day") or "").strip(),
        (payload.get("dob_year") or "").strip(),
        (payload.get("gender") or "").strip(),
        old_trn,
        normalized_contact,
        (payload.get("overseas_registrant") or "").strip(),
        (payload.get("gov_ayuda_programs") or "").strip(),
        (payload.get("authenticated_status") or "").strip(),
        record_type,
        (payload.get("philid_ephilid_presented") or "").strip(),
        (payload.get("change_correction") or "").strip(),
        (payload.get("supporting_document") or "").strip(),
        (payload.get("fields_changed") or "").strip(),
        (payload.get("national_id_form_presented") or "").strip(),
    )
    db = get_db()
    if entry_id is None:
        cursor = db.execute(
            """
            INSERT INTO data_entries
            (reporting_date, city_municipality, barangay, specific_location, type_of_rc,
             rko_employee_id, applicant_first_name, applicant_middle_name, applicant_last_name,
             applicant_suffix, trn_or_pcn, age_category, service_availed, ephilid_status,
             ephilid_issued_date, digital_id_assistance, digital_id_generated, digital_id_issue_notes,
             dob_month, dob_day, dob_year, gender, old_trn, contact_number, overseas_registrant,
             gov_ayuda_programs, authenticated_status, record_type, philid_ephilid_presented,
             change_correction, supporting_document, fields_changed, national_id_form_presented,
             created_by_user_id, created_by_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*fields, created_by_user_id, created_by_name),
        )
        db.commit()
        return cursor.lastrowid
    db.execute(
        """
        UPDATE data_entries
        SET reporting_date=?, city_municipality=?, barangay=?, specific_location=?, type_of_rc=?,
            rko_employee_id=?, applicant_first_name=?, applicant_middle_name=?,
            applicant_last_name=?, applicant_suffix=?, trn_or_pcn=?, age_category=?, service_availed=?,
            ephilid_status=?, ephilid_issued_date=?, digital_id_assistance=?, digital_id_generated=?,
            digital_id_issue_notes=?, dob_month=?, dob_day=?, dob_year=?, gender=?, old_trn=?,
            contact_number=?, overseas_registrant=?, gov_ayuda_programs=?, authenticated_status=?,
            record_type=?, philid_ephilid_presented=?, change_correction=?, supporting_document=?,
            fields_changed=?, national_id_form_presented=?
        WHERE id=?
        """,
        (*fields, entry_id),
    )
    db.commit()
    return entry_id


def delete_data_entry(entry_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM data_entries WHERE id = ?", (entry_id,))
    db.commit()


def mark_data_entries_sent_to_sheet(entry_ids: Iterable[int]) -> None:
    entry_ids = [int(i) for i in entry_ids]
    if not entry_ids:
        return
    db = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    placeholders = ",".join("?" for _ in entry_ids)
    db.execute(
        f"UPDATE data_entries SET sent_to_sheet = 1, sent_to_sheet_at = ? "
        f"WHERE id IN ({placeholders})",
        (now, *entry_ids),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Entry Defaults -- per-user auto-lock defaults for the Data Entry form.
# Each RKO/user can pre-fill and optionally lock (read-only, auto-input)
# specific fields for themselves -- e.g. their own name as RKO, today's
# date, their usual city/barangay -- so they don't have to retype the
# same values on every entry. Locking is entirely up to the user.
# ---------------------------------------------------------------------------

ENTRY_DEFAULT_FIELDS = (
    "city_municipality",
    "barangay",
    "specific_location",
    "type_of_rc",
    "rko_employee_id",
)

# reporting_date_mode: "blank" (leave the date empty as before) or
# "today" (always pre-fill with today's date).
REPORTING_DATE_MODES = ["blank", "today"]


def get_entry_defaults(user_id: int):
    if not user_id:
        return None
    return get_db().execute(
        "SELECT * FROM entry_defaults WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def save_entry_defaults(user_id: int, payload: dict) -> None:
    if not user_id:
        raise ValueError("A logged-in user is required to save entry defaults.")

    def _locked(name: str) -> int:
        return 1 if payload.get(f"{name}_locked") else 0

    reporting_date_mode = (payload.get("reporting_date_mode") or "blank").strip()
    if reporting_date_mode not in REPORTING_DATE_MODES:
        reporting_date_mode = "blank"

    # A field can only be locked once the RKO/RA has actually selected or
    # entered a value for it -- locking a still-blank field would just
    # auto-input nothing, silently forcing every new entry to be missing
    # that field. This applies equally to every user regardless of RKO/RA.
    FIELD_LABELS = {
        "city_municipality": "City / Municipality",
        "barangay": "Barangay",
        "specific_location": "Specific Location",
        "type_of_rc": "Type of RC",
        "rko_employee_id": "Name of RKO",
    }
    for field, label in FIELD_LABELS.items():
        if _locked(field) and not (payload.get(field) or "").strip():
            raise ValueError(f'Select a value for "{label}" before you can lock it.')
    if _locked("reporting_date") and reporting_date_mode != "today":
        raise ValueError(
            'Choose "Always today\'s date" for Reporting Date before you can lock it '
            '(you can\'t lock a date that\'s left blank).'
        )

    rko_employee_id = payload.get("rko_employee_id") or None

    values = {
        "city_municipality": _upper_text(payload.get("city_municipality")),
        "city_municipality_locked": _locked("city_municipality"),
        "barangay": _upper_text(payload.get("barangay")),
        "barangay_locked": _locked("barangay"),
        "specific_location": _title_text(payload.get("specific_location")),
        "specific_location_locked": _locked("specific_location"),
        "type_of_rc": _upper_text(payload.get("type_of_rc")),
        "type_of_rc_locked": _locked("type_of_rc"),
        "rko_employee_id": int(rko_employee_id) if rko_employee_id else None,
        "rko_employee_id_locked": _locked("rko_employee_id"),
        "reporting_date_mode": reporting_date_mode,
        "reporting_date_locked": _locked("reporting_date"),
    }

    db = get_db()
    existing = get_entry_defaults(user_id)
    if existing is None:
        db.execute(
            """
            INSERT INTO entry_defaults
            (user_id, city_municipality, city_municipality_locked, barangay, barangay_locked,
             specific_location, specific_location_locked, type_of_rc, type_of_rc_locked,
             rko_employee_id, rko_employee_id_locked, reporting_date_mode, reporting_date_locked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                values["city_municipality"], values["city_municipality_locked"],
                values["barangay"], values["barangay_locked"],
                values["specific_location"], values["specific_location_locked"],
                values["type_of_rc"], values["type_of_rc_locked"],
                values["rko_employee_id"], values["rko_employee_id_locked"],
                values["reporting_date_mode"], values["reporting_date_locked"],
            ),
        )
    else:
        db.execute(
            """
            UPDATE entry_defaults
            SET city_municipality=?, city_municipality_locked=?, barangay=?, barangay_locked=?,
                specific_location=?, specific_location_locked=?, type_of_rc=?, type_of_rc_locked=?,
                rko_employee_id=?, rko_employee_id_locked=?, reporting_date_mode=?,
                reporting_date_locked=?, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=?
            """,
            (
                values["city_municipality"], values["city_municipality_locked"],
                values["barangay"], values["barangay_locked"],
                values["specific_location"], values["specific_location_locked"],
                values["type_of_rc"], values["type_of_rc_locked"],
                values["rko_employee_id"], values["rko_employee_id_locked"],
                values["reporting_date_mode"], values["reporting_date_locked"],
                user_id,
            ),
        )
    db.commit()


def resolve_entry_defaults_for_form(user_id: int) -> tuple[dict, set[str]]:
    """Returns (default_values, locked_field_names) for building a fresh
    (non-edit) Data Entry form for this user. Fields the user has locked
    come back pre-filled and are also reported in the locked set so the
    view/template can render them read-only and the save step can enforce
    the locked value server-side, regardless of what the client submits."""
    defaults = get_entry_defaults(user_id)
    values: dict = {}
    locked: set[str] = set()
    if not defaults:
        return values, locked

    for field in ENTRY_DEFAULT_FIELDS:
        if defaults[field] not in (None, ""):
            values[field] = defaults[field]
        if defaults[f"{field}_locked"]:
            locked.add(field)

    if defaults["reporting_date_mode"] == "today":
        values["reporting_date"] = datetime.now().strftime("%Y-%m-%d")
    if defaults["reporting_date_locked"]:
        locked.add("reporting_date")

    return values, locked


def list_signatories() -> list:
    return get_db().execute(
        """
        SELECT id, report_type, role, name, position
        FROM signatories
        ORDER BY report_type ASC, role ASC, name ASC
        """
    ).fetchall()


def get_signatory(signatory_id: int):
    return get_db().execute(
        """
        SELECT id, report_type, role, name, position
        FROM signatories WHERE id = ?
        """,
        (signatory_id,),
    ).fetchone()


def save_signatory(signatory_id: int | None, payload: dict) -> None:
    db = get_db()
    fields = (
        payload.get("report_type", "general").strip() or "general",
        payload["role"].strip(),
        _upper_text(payload["name"]),
        _upper_text(payload["position"]),
    )
    if signatory_id is None:
        db.execute(
            """
            INSERT INTO signatories (report_type, role, name, position)
            VALUES (?, ?, ?, ?)
            """,
            fields,
        )
    else:
        db.execute(
            """
            UPDATE signatories
            SET report_type=?, role=?, name=?, position=?
            WHERE id=?
            """,
            (*fields, signatory_id),
        )
    db.commit()


def delete_signatory(signatory_id: int) -> None:
    db = get_db()
    db.execute("DELETE FROM signatories WHERE id = ?", (signatory_id,))
    db.commit()


def monthly_city_records(month: str) -> list:
    return get_db().execute(
        """
        SELECT
            COALESCE(NULLIF(o.city_municipality, ''), NULLIF(e.city_municipality, ''), 'Unassigned') AS city_municipality,
            lower(o.category) AS category_key,
            COUNT(DISTINCT o.employee_id) AS employees,
            SUM(o.quantity) AS total_quantity
        FROM employee_outputs o
        JOIN employees e ON e.id = o.employee_id
        WHERE substr(o.work_date, 1, 7) = ?
        GROUP BY COALESCE(NULLIF(o.city_municipality, ''), NULLIF(e.city_municipality, ''), 'Unassigned'), lower(o.category)
        ORDER BY city_municipality ASC, category_key ASC
        """,
        (month,),
    ).fetchall()


def city_service_rows(
    filters: dict | None = None,
    city_municipalities: list[str] | None = None,
) -> list[dict]:
    """Per-city service summary with Male/Female/Total per service.

    Ensures all ``city_municipalities`` are present even with zero records.
    """
    filters = filters or {}
    sql = """
        SELECT
            COALESCE(NULLIF(o.city_municipality, ''), NULLIF(e.city_municipality, ''), 'Unassigned') AS city_municipality,
            COALESCE(NULLIF(o.activity_type, ''), '') AS activity_type,
            lower(COALESCE(o.sex, '')) AS sex_key,
            SUM(o.quantity) AS qty
        FROM employee_outputs o
        JOIN employees e ON e.id = o.employee_id
        WHERE 1 = 1
    """
    params: list = []
    if filters.get("start_date"):
        sql += " AND o.work_date >= ?"
        params.append(filters["start_date"])
    if filters.get("end_date"):
        sql += " AND o.work_date <= ?"
        params.append(filters["end_date"])
    sql += """
        GROUP BY
            COALESCE(NULLIF(o.city_municipality, ''), NULLIF(e.city_municipality, ''), 'Unassigned'),
            COALESCE(NULLIF(o.activity_type, ''), ''),
            lower(COALESCE(o.sex, ''))
    """

    raw_rows = get_db().execute(sql, params).fetchall()

    def _norm_city(city: str) -> str:
        return (city or "").strip().upper()

    base_cities = city_municipalities or []
    ordered_keys = [_norm_city(city) for city in base_cities if (city or "").strip()]
    key_to_display = {_norm_city(city): city for city in base_cities if (city or "").strip()}

    by_city: dict[str, dict] = {}
    for row in raw_rows:
        city_display = (row["city_municipality"] or "Unassigned").strip() or "Unassigned"
        city_key = _norm_city(city_display) or "UNASSIGNED"
        if city_key not in by_city:
            by_city[city_key] = {
                "city_municipality": key_to_display.get(city_key, city_display),
                "services": {
                    service: {"male": 0, "female": 0, "total": 0}
                    for service in SERVICE_TYPES
                },
                "male": 0,
                "female": 0,
                "total": 0,
            }
        activity = (row["activity_type"] or "").strip()
        if activity not in SERVICE_TYPES:
            continue
        qty = int(row["qty"] or 0)
        sex_key = (row["sex_key"] or "").strip().lower()
        slot = by_city[city_key]["services"][activity]
        slot["total"] += qty
        by_city[city_key]["total"] += qty
        if sex_key == "male":
            slot["male"] += qty
            by_city[city_key]["male"] += qty
        elif sex_key == "female":
            slot["female"] += qty
            by_city[city_key]["female"] += qty

    # Ensure official city list appears even without rows.
    for city in base_cities:
        city_key = _norm_city(city)
        if city_key not in by_city:
            by_city[city_key] = {
                "city_municipality": city,
                "services": {
                    service: {"male": 0, "female": 0, "total": 0}
                    for service in SERVICE_TYPES
                },
                "male": 0,
                "female": 0,
                "total": 0,
            }

    extras = sorted([k for k in by_city.keys() if k not in set(ordered_keys)])
    ordered = ordered_keys + extras
    return [by_city[k] for k in ordered]


def employee_monthly_summary(employee_id: int, month: str, category: str | None = None) -> list:
    sql = """
        SELECT work_date, category, activity_type, quantity, remarks,
               COALESCE(NULLIF(city_municipality, ''), '') AS city_municipality,
               COALESCE(NULLIF(province, ''), '') AS province
        FROM employee_outputs
        WHERE employee_id = ? AND substr(work_date, 1, 7) = ?
    """
    params: list = [employee_id, month]
    if category:
        sql += " AND lower(category) = lower(?)"
        params.append(category)
    sql += " ORDER BY work_date ASC, id ASC"
    return get_db().execute(sql, params).fetchall()


def employee_date_summary(
    employee_id: int,
    start_date: str,
    end_date: str,
    category: str | None = None,
) -> list:
    sql = """
        SELECT work_date, category, activity_type, quantity, remarks,
               COALESCE(NULLIF(city_municipality, ''), '') AS city_municipality,
               COALESCE(NULLIF(province, ''), '') AS province
        FROM employee_outputs
        WHERE employee_id = ? AND work_date >= ? AND work_date <= ?
    """
    params: list = [employee_id, start_date, end_date]
    if category:
        sql += " AND lower(category) = lower(?)"
        params.append(category)
    sql += " ORDER BY work_date ASC, id ASC"
    return get_db().execute(sql, params).fetchall()


def _normalize_signatory_role(role_raw: str | None) -> str | None:
    """Map DB role strings to prepared_by / verified_by (handles minor typos)."""
    r = (role_raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if r in ("prepared_by", "preparedby"):
        return "prepared_by"
    if r in ("verified_by", "verifiedby"):
        return "verified_by"
    if "verify" in r:
        return "verified_by"
    if "prepared" in r:
        return "prepared_by"
    return None


def signatories_for_report(report_type: str) -> dict[str, dict]:
    """Resolve signatories by role for a report. Prefer the most specific `report_type`, then `general`.

    Employee Output Summary uses ``report_type='output'``. Signatories may be stored as ``output``,
    ``delivery`` (legacy), ``registration``, or ``general`` — merged with priority order.

    If the report-specific row exists but has an empty name or position, merge from the next
    matching row so the same rules apply to PDF and HTML preview.
    """
    db = get_db()
    rt = (report_type or "general").strip().lower()

    if rt == "output":
        rows = db.execute(
            """
            SELECT role, name, position, report_type
            FROM signatories
            WHERE report_type IN ('output', 'delivery', 'registration', 'general')
            ORDER BY
                CASE report_type
                    WHEN 'output' THEN 0
                    WHEN 'delivery' THEN 1
                    WHEN 'registration' THEN 2
                    WHEN 'general' THEN 3
                    ELSE 4
                END,
                role ASC
            """
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT role, name, position, report_type
            FROM signatories
            WHERE report_type IN (?, 'general')
            ORDER BY CASE WHEN report_type = ? THEN 0 ELSE 1 END, role ASC
            """,
            (rt, rt),
        ).fetchall()

    result: dict[str, dict] = {}
    for row in rows:
        role_key = _normalize_signatory_role(row["role"])
        if not role_key:
            continue
        name = (row["name"] or "").strip()
        position = (row["position"] or "").strip()
        if role_key not in result:
            result[role_key] = {"name": row["name"] or "", "position": row["position"] or ""}
            continue
        cur = result[role_key]
        if not (cur.get("name") or "").strip() and name:
            cur["name"] = row["name"] or ""
        if not (cur.get("position") or "").strip() and position:
            cur["position"] = row["position"] or ""

    # Fallback for installations where "Verified as correct by" was saved as a
    # Focal Person row but not tagged with role=verified_by.
    verified = result.get("verified_by") or {}
    if not (verified.get("name") or "").strip():
        for row in rows:
            role_raw = (row["role"] or "").strip().lower()
            name = (row["name"] or "").strip()
            position = (row["position"] or "").strip()
            if not name:
                continue
            if role_raw == "verified_by" or "focal person" in position.lower():
                result["verified_by"] = {"name": row["name"] or "", "position": position or "Focal Person"}
                break

    # Last resort: newest signatory row whose role maps to verified_by (any report_type)
    if not ((result.get("verified_by") or {}).get("name") or "").strip():
        for row in db.execute(
            "SELECT role, name, position FROM signatories ORDER BY id DESC"
        ).fetchall():
            if _normalize_signatory_role(row["role"]) == "verified_by" and (row["name"] or "").strip():
                result["verified_by"] = {
                    "name": row["name"] or "",
                    "position": (row["position"] or "") or "Focal Person",
                }
                break
    return result


def find_employee_by_code_or_name(employee_code: str | None, full_name: str | None):
    db = get_db()
    if employee_code:
        row = db.execute(
            "SELECT * FROM employees WHERE employee_code = ?",
            (employee_code.strip(),),
        ).fetchone()
        if row:
            return row
    if full_name:
        return db.execute(
            "SELECT * FROM employees WHERE lower(full_name) = lower(?)",
            (full_name.strip(),),
        ).fetchone()
    return None


def create_employee_if_missing(payload: dict):
    employee = find_employee_by_code_or_name(
        payload.get("employee_code"), payload.get("full_name")
    )
    if employee:
        return employee["id"]

    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO employees (employee_code, full_name, position, province, city_municipality, active)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (
            payload.get("employee_code") or None,
            _upper_text(payload["full_name"]),
            _upper_text(payload.get("position")),
            _upper_text(payload.get("province")),
            _upper_text(payload.get("city_municipality")),
        ),
    )
    db.commit()
    return cursor.lastrowid


def bulk_insert_outputs(rows: Iterable[dict]) -> int:
    db = get_db()
    inserted = 0
    for row in rows:
        db.execute(
            """
            INSERT OR IGNORE INTO employee_outputs
            (employee_id, work_date, category, activity_type, sex, quantity, remarks,
             province, city_municipality, source_ref, source_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["employee_id"],
                row["work_date"],
                _upper_text(row["category"]),
                row.get("activity_type", ""),
                _upper_text(row.get("sex", "")),
                int(row.get("quantity", 0) or 0),
                _upper_text(row.get("remarks", "")),
                _upper_text(row.get("province", "")),
                _upper_text(row.get("city_municipality", "")),
                row.get("source_ref", ""),
                row.get("source_key") or None,
            ),
        )
        if db.execute("SELECT changes()").fetchone()[0]:
            inserted += 1
    db.commit()
    return inserted


def delete_imported_outputs(source_type: str = "all") -> int:
    db = get_db()
    if source_type == "google_sheet":
        cursor = db.execute(
            """
            DELETE FROM employee_outputs
            WHERE source_ref LIKE 'https://docs.google.com/spreadsheets/%'
               OR source_ref LIKE 'https://docs.google.com/%'
            """
        )
    elif source_type == "apps_script":
        cursor = db.execute(
            """
            DELETE FROM employee_outputs
            WHERE source_ref LIKE 'https://script.google.com/%'
            """
        )
    else:
        cursor = db.execute(
            """
            DELETE FROM employee_outputs
            WHERE source_ref IS NOT NULL AND trim(source_ref) <> ''
            """
        )
    db.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# NID Concern Matrix
# ---------------------------------------------------------------------------

NID_CONCERN_TYPES = [
    "Request ID not found",
    "Unclickable",
    "OSI Validate",
    "Validate Packet",
    "Manual Verification",
    "Upload Packets",
    "Biometric Verification/ Authentication",
    "Demographic Verification/ Authentication",
    "Biographic Verification/ Authentication",
    "Verify Packet",
    "Could Not Track",
    "EPhilID Password Request",
    "No QR /Photo",
]

def nid_concern_monthly_matrix(month: str) -> list:
    """Concern-type x status breakdown for a single month (YYYY-MM) --
    same shape as nid_concern_matrix_summary() but scoped to one month."""
    rows = [r for r in sheets_db.get_all("NidConcerns") if (r.get("date_reported") or "").startswith(month)]
    matrix: dict[str, dict[str, int]] = {
        concern_type: {status: 0 for status in NID_CONCERN_STATUSES} for concern_type in NID_CONCERN_TYPES
    }
    for row in rows:
        concern_type = row.get("concern_type") or "Other"
        status = row.get("status") or "Open"
        matrix.setdefault(concern_type, {s: 0 for s in NID_CONCERN_STATUSES})
        matrix[concern_type].setdefault(status, 0)
        matrix[concern_type][status] += 1
    return [
        {"concern_type": concern_type, **counts, "total": sum(counts.values())}
        for concern_type, counts in matrix.items()
    ]


def nid_concern_monthly_trend(months: int = 6, end_month: str | None = None) -> list:
    """Per-month statistics (counts by status, total, resolution rate) for
    the `months` months ending with `end_month` (YYYY-MM, defaults to the
    current month) -- oldest first, so it reads left-to-right as a trend."""
    end_month = end_month or datetime.now().strftime("%Y-%m")
    end_year, end_mon = (int(part) for part in end_month.split("-"))

    month_keys = []
    year, mon = end_year, end_mon
    for _ in range(max(months, 1)):
        month_keys.append(f"{year:04d}-{mon:02d}")
        mon -= 1
        if mon == 0:
            mon = 12
            year -= 1
    month_keys.reverse()

    counts_by_month = {mk: {status: 0 for status in NID_CONCERN_STATUSES} for mk in month_keys}
    for row in sheets_db.get_all("NidConcerns"):
        mk = (row.get("date_reported") or "")[:7]
        if mk in counts_by_month:
            status = row.get("status") or "Open"
            counts_by_month[mk].setdefault(status, 0)
            counts_by_month[mk][status] += 1

    trend = []
    for mk in month_keys:
        counts = counts_by_month[mk]
        total = sum(counts.values())
        resolved = counts.get("Resolved", 0)
        resolution_rate = round((resolved / total) * 100, 1) if total else 0.0
        trend.append({"month": mk, **counts, "total": total, "resolution_rate": resolution_rate})
    return trend


NID_CONCERN_STATUSES = ["Open", "In Progress", "Resolved", "Escalated"]

# Drives the progress bar shown on each ticket -- updated whenever an
# Information Systems Analyst changes the ticket's status.
NID_CONCERN_STATUS_PROGRESS = {
    "Open": 10,
    "In Progress": 55,
    "Escalated": 75,
    "Resolved": 100,
}

TRN_REF_NO_PATTERN = re.compile(r"^\d{29}$")


def is_valid_trn_ref_no(value: str) -> bool:
    return bool(TRN_REF_NO_PATTERN.match((value or "").strip()))


def normalize_mobile_number(value: str) -> str | None:
    """Normalize a Philippine mobile number to 09XXXXXXXXX (11 digits).
    Accepts 09171234567, +639171234567, 639171234567, or with spaces/
    dashes. Returns None if it doesn't resolve to a valid PH mobile number."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    if re.fullmatch(r"09\d{9}", digits):
        return digits
    return None


def list_nid_concerns(filters: dict | None = None) -> list:
    filters = filters or {}
    rows = sheets_db.get_all("NidConcerns")
    if filters.get("status"):
        rows = [r for r in rows if r.get("status") == filters["status"]]
    if filters.get("concern_type"):
        rows = [r for r in rows if r.get("concern_type") == filters["concern_type"]]
    if filters.get("city_municipality"):
        rows = [r for r in rows if r.get("city_municipality") == filters["city_municipality"]]
    if filters.get("start_date"):
        rows = [r for r in rows if (r.get("date_reported") or "") >= filters["start_date"]]
    if filters.get("end_date"):
        rows = [r for r in rows if (r.get("date_reported") or "") <= filters["end_date"]]
    rows.sort(key=lambda r: (r.get("date_reported") or "", r.get("id") or 0), reverse=True)
    return rows


def nid_concern_matrix_summary() -> list:
    """Rows/columns matrix: concern type x status, with counts -- powers the
    dashboard's NID Concern Matrix data table."""
    matrix: dict[str, dict[str, int]] = {
        concern_type: {status: 0 for status in NID_CONCERN_STATUSES} for concern_type in NID_CONCERN_TYPES
    }
    for row in sheets_db.get_all("NidConcerns"):
        concern_type = row.get("concern_type") or "Other"
        status = row.get("status") or "Open"
        matrix.setdefault(concern_type, {s: 0 for s in NID_CONCERN_STATUSES})
        matrix[concern_type].setdefault(status, 0)
        matrix[concern_type][status] += 1
    return [
        {"concern_type": concern_type, **counts, "total": sum(counts.values())}
        for concern_type, counts in matrix.items()
    ]


def get_nid_concern(concern_id: int):
    return sheets_db.get_by_id("NidConcerns", concern_id)


def create_nid_concern(form, reporter_user_id: int, reporter_full_name: str) -> int:
    """Log a new ticket. `reported_by` is always taken from the logged-in
    user, never from free text, and the reference number must be exactly
    29 digits."""
    trn_or_ref_no = (form.get("trn_or_ref_no") or "").strip()
    if not is_valid_trn_ref_no(trn_or_ref_no):
        raise ValueError("TRN / Reference No. must be exactly 29 digits.")
    mobile_number = normalize_mobile_number(form.get("mobile_number"))
    if not mobile_number:
        raise ValueError("A valid mobile number is required (e.g. 09171234567).")
    return sheets_db.insert(
        "NidConcerns",
        {
            "date_reported": form.get("date_reported") or datetime.now().strftime("%Y-%m-%d"),
            "city_municipality": "",
            "trn_or_ref_no": trn_or_ref_no,
            "concern_type": (form.get("concern_type") or NID_CONCERN_TYPES[0]).strip(),
            "description": _title_text(form.get("description")),
            "status": "Open",
            "reported_by": reporter_full_name,
            "reported_by_user_id": reporter_user_id,
            "remarks": "",
            "mobile_number": mobile_number,
            "client_informed": 0,
        },
    )


def update_nid_concern_status(concern_id: int, status: str) -> None:
    """Only an Information Systems Analyst (or Administrator) should call
    this -- enforced at the view layer with roles_required."""
    if status not in NID_CONCERN_STATUSES:
        raise ValueError("Unknown status.")
    values = {"status": status}
    if status == "Resolved":
        # Fresh acknowledgment needed each time a ticket becomes Resolved --
        # if it gets reopened and resolved again later, the reporting user
        # is notified again too.
        values["client_informed"] = 0
    sheets_db.update("NidConcerns", concern_id, values)


def mark_concern_client_informed(concern_id: int) -> None:
    """Reporting user confirms they've told the client their concern was
    resolved -- clears the notification/reminder for this ticket."""
    sheets_db.update("NidConcerns", concern_id, {"client_informed": 1})


def list_pending_client_notifications(user_id: int) -> list:
    """Tickets this user reported that are Resolved but they haven't yet
    confirmed telling the client -- powers the notification badge/banner."""
    rows = [
        row
        for row in sheets_db.get_all("NidConcerns")
        if row.get("reported_by_user_id") == int(user_id)
        and row.get("status") == "Resolved"
        and not row.get("client_informed")
    ]
    rows.sort(key=lambda r: (r.get("date_reported") or "", r.get("id") or 0), reverse=True)
    return rows


def update_nid_concern(concern_id: int, form) -> None:
    """Edit a ticket's core fields (date, TRN/reference no., type, description).
    Status is changed separately via update_nid_concern_status."""
    trn_or_ref_no = (form.get("trn_or_ref_no") or "").strip()
    if not is_valid_trn_ref_no(trn_or_ref_no):
        raise ValueError("TRN / Reference No. must be exactly 29 digits.")
    mobile_number = normalize_mobile_number(form.get("mobile_number"))
    if not mobile_number:
        raise ValueError("A valid mobile number is required (e.g. 09171234567).")
    concern_type = (form.get("concern_type") or "").strip()
    if concern_type not in NID_CONCERN_TYPES:
        raise ValueError("Unknown concern type.")
    date_reported = (form.get("date_reported") or "").strip()
    if not date_reported:
        raise ValueError("Date reported is required.")
    sheets_db.update(
        "NidConcerns",
        concern_id,
        {
            "date_reported": date_reported,
            "trn_or_ref_no": trn_or_ref_no,
            "concern_type": concern_type,
            "description": _title_text(form.get("description")),
            "mobile_number": mobile_number,
        },
    )


def nid_concern_progress(status: str) -> int:
    return NID_CONCERN_STATUS_PROGRESS.get(status, 0)


def delete_nid_concern(concern_id: int) -> None:
    sheets_db.delete("NidConcerns", concern_id)
    # No FK cascade in a spreadsheet -- clean up the ticket's thread by hand.
    for message in sheets_db.find("ConcernMessages", concern_id=concern_id):
        sheets_db.delete("ConcernMessages", message["id"])


# ---------------------------------------------------------------------------
# Ticket thread messages (Information Systems Analyst <-> reporting user)
# ---------------------------------------------------------------------------

def list_concern_messages(concern_id: int) -> list:
    rows = sheets_db.find("ConcernMessages", concern_id=concern_id)
    users_by_id = {u["id"]: u for u in sheets_db.get_all("Users")}
    for row in rows:
        sender = users_by_id.get(row.get("sender_id"))
        row["sender_name"] = sender["full_name"] if sender else "Unknown"
        row["sender_role"] = sender["role"] if sender else ""
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or 0))
    return rows


def add_concern_message(concern_id: int, sender_id: int, body: str) -> None:
    body = (body or "").strip()
    if not body:
        return
    sheets_db.insert("ConcernMessages", {"concern_id": concern_id, "sender_id": sender_id, "body": body})


def user_can_view_concern(concern, user_id: int, role: str) -> bool:
    if role in (ROLE_ADMIN, ROLE_ISA):
        return True
    return concern is not None and concern.get("reported_by_user_id") == user_id


# ---------------------------------------------------------------------------
# User accounts
# ---------------------------------------------------------------------------

def list_users() -> list:
    rows = sheets_db.get_all("Users")
    rows.sort(key=lambda r: (r.get("full_name") or "").lower())
    return rows


def list_active_users(exclude_user_id: int | None = None) -> list:
    rows = [r for r in sheets_db.get_all("Users") if r.get("active")]
    if exclude_user_id is not None:
        rows = [r for r in rows if r.get("id") != int(exclude_user_id)]
    rows.sort(key=lambda r: (r.get("full_name") or "").lower())
    return rows


def get_user(user_id: int):
    return sheets_db.get_by_id("Users", user_id)


def get_user_by_username(username: str):
    username = (username or "").strip().lower()
    if not username:
        return None
    for row in sheets_db.get_all("Users"):
        if (row.get("username") or "").strip().lower() == username:
            return row
    return None


def create_user(username: str, password: str, full_name: str, role: str) -> None:
    username = (username or "").strip()
    full_name = _title_text(full_name)
    if not username or not password or not full_name:
        raise ValueError("Username, password, and full name are required.")
    if role not in ROLES:
        raise ValueError("Unknown role.")
    if get_user_by_username(username):
        raise ValueError("A user with that username already exists.")
    sheets_db.insert(
        "Users",
        {
            "username": username,
            "password_hash": generate_password_hash(password),
            "full_name": full_name,
            "role": role,
            "active": 1,
        },
    )


def update_user(user_id: int, full_name: str, role: str, active: bool, new_password: str | None = None) -> None:
    if role not in ROLES:
        raise ValueError("Unknown role.")
    values = {
        "full_name": _title_text(full_name),
        "role": role,
        "active": 1 if active else 0,
    }
    if new_password:
        values["password_hash"] = generate_password_hash(new_password)
    sheets_db.update("Users", user_id, values)


# ---------------------------------------------------------------------------
# Direct 1-on-1 messenger -- messages auto-delete 10 hours after being sent
# ---------------------------------------------------------------------------

DIRECT_MESSAGE_LIFETIME = timedelta(hours=10)


def _purge_expired_direct_messages() -> None:
    cutoff = (datetime.now() - DIRECT_MESSAGE_LIFETIME).strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    db.execute("DELETE FROM direct_messages WHERE created_at < ?", (cutoff,))
    db.commit()


# Public alias so a background scheduler (see app/scheduler.py) can trigger
# the purge on a timer, instead of only ever purging lazily whenever someone
# happens to open/poll the Messages page. Same function either way.
purge_expired_direct_messages = _purge_expired_direct_messages


def list_conversation(user_a_id: int, user_b_id: int) -> list:
    _purge_expired_direct_messages()
    rows = get_db().execute(
        """
        SELECT *
        FROM direct_messages
        WHERE (sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?)
        ORDER BY created_at ASC, id ASC
        """,
        (user_a_id, user_b_id, user_b_id, user_a_id),
    ).fetchall()
    users_by_id = {u["id"]: u for u in sheets_db.get_all("Users")}
    result = []
    for row in rows:
        item = dict(row)
        sender = users_by_id.get(item["sender_id"])
        item["sender_name"] = sender["full_name"] if sender else "Unknown"
        result.append(item)
    return result


def send_direct_message(sender_id: int, recipient_id: int, body: str) -> None:
    body = (body or "").strip()
    if not body:
        return
    _purge_expired_direct_messages()
    db = get_db()
    db.execute(
        "INSERT INTO direct_messages (sender_id, recipient_id, body) VALUES (?, ?, ?)",
        (sender_id, recipient_id, body),
    )
    db.commit()


def unread_dm_counts_by_sender(recipient_id: int) -> dict[int, int]:
    """Not true read/unread tracking (kept simple) -- returns message counts
    per conversation partner in the last 10 hours, useful for a contact list
    badge."""
    _purge_expired_direct_messages()
    rows = get_db().execute(
        """
        SELECT sender_id, COUNT(*) AS n
        FROM direct_messages
        WHERE recipient_id = ?
        GROUP BY sender_id
        """,
        (recipient_id,),
    ).fetchall()
    return {row["sender_id"]: row["n"] for row in rows}
