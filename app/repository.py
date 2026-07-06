from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

from werkzeug.security import generate_password_hash

from . import sheets_db
from .db import ROLE_ADMIN, ROLE_ISA, ROLE_USER, ROLES, get_db


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
]


def _upper_text(value: str | None) -> str:
    return (value or "").strip().upper()


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
    return get_db().execute(
        """
        SELECT id, source_type, original_url, normalized_url, method, payload,
               last_check_at, last_status, last_error, rows_imported, created_at
        FROM import_sources
        ORDER BY created_at DESC
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
                rows_imported = COALESCE(?, rows_imported)
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
                existing["id"],
            ),
        )
        db.commit()
        return existing["id"]

    cursor = db.execute(
        """
        INSERT INTO import_sources
        (source_type, original_url, normalized_url, method, payload,
         last_check_at, last_status, last_error, rows_imported)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ),
    )
    db.commit()
    return cursor.lastrowid


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
]

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
    return sheets_db.insert(
        "NidConcerns",
        {
            "date_reported": form.get("date_reported") or datetime.now().strftime("%Y-%m-%d"),
            "city_municipality": "",
            "trn_or_ref_no": trn_or_ref_no,
            "concern_type": (form.get("concern_type") or NID_CONCERN_TYPES[0]).strip(),
            "description": (form.get("description") or "").strip(),
            "status": "Open",
            "reported_by": reporter_full_name,
            "reported_by_user_id": reporter_user_id,
            "remarks": "",
        },
    )


def update_nid_concern_status(concern_id: int, status: str) -> None:
    """Only an Information Systems Analyst (or Administrator) should call
    this -- enforced at the view layer with roles_required."""
    if status not in NID_CONCERN_STATUSES:
        raise ValueError("Unknown status.")
    sheets_db.update("NidConcerns", concern_id, {"status": status})


def update_nid_concern(concern_id: int, form) -> None:
    """Edit a ticket's core fields (date, TRN/reference no., type, description).
    Status is changed separately via update_nid_concern_status."""
    trn_or_ref_no = (form.get("trn_or_ref_no") or "").strip()
    if not is_valid_trn_ref_no(trn_or_ref_no):
        raise ValueError("TRN / Reference No. must be exactly 29 digits.")
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
            "description": (form.get("description") or "").strip(),
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
    full_name = (full_name or "").strip()
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
        "full_name": (full_name or "").strip(),
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
