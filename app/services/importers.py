from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen

import requests

from ..repository import (
    SERVICE_TYPES,
    bulk_insert_outputs,
    create_employee_if_missing,
    list_import_sources,
    save_import_source,
)

SERVICE_TYPE_SET = set(SERVICE_TYPES)


def _normalize_key(key: str) -> str:
    return (
        key.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


def _parse_date(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("Missing date value.")

    formats = [
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%b %d, %Y",
        "%B %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    try:
        serial = float(value)
        excel_origin = datetime(1899, 12, 30)
        return (excel_origin + timedelta(days=serial)).strftime("%Y-%m-%d")
    except Exception as exc:
        raise ValueError(f"Unsupported date format: {raw_value}") from exc


def _pick(record: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        if key in record and str(record[key]).strip():
            return str(record[key]).strip()
    return default


def _normalize_record(raw: dict, source_ref: str) -> dict:
    record = {_normalize_key(k): v for k, v in raw.items()}
    employee_name = _pick(
        record,
        "name_of_rko",
        "employee",
        "employee_name",
        "full_name",
        "name",
        "personnel",
    )
    if not employee_name:
        raise ValueError("Employee name is required in imported data.")

    quantity_raw = _pick(record, "quantity", "qty", "count", "total", "output", default="1")
    try:
        quantity = int(float(quantity_raw or 1))
    except ValueError:
        quantity = 1

    service_name = _pick(record, "services_availed", "activity_type", "activity", "service")
    if service_name not in SERVICE_TYPE_SET:
        raise ValueError("Unsupported service type.")
    ephilid_status = _pick(record, "ephilid_status")
    remarks = _pick(record, "remarks", "remark", "notes")
    if ephilid_status:
        remarks = f"ePhilID Status: {ephilid_status}" if not remarks else f"{remarks} | ePhilID Status: {ephilid_status}"

    normalized = {
        "employee_code": _pick(record, "employee_code", "code", "employee_id"),
        "full_name": employee_name,
        "position": _pick(record, "position", "designation"),
        "province": _pick(record, "province", default="Cavite"),
        "city_municipality": _pick(record, "city_municipality", "city_municipality_", "city", "municipality"),
        "work_date": _parse_date(_pick(record, "timestamp", "date", "work_date", "transaction_date")),
        "category": _infer_category(service_name, ephilid_status),
        "activity_type": service_name,
        "sex": _pick(record, "sex"),
        "quantity": quantity,
        "remarks": remarks,
        "source_ref": source_ref,
        "source_key": _build_source_key(record, employee_name, service_name),
    }
    return normalized


def _infer_category(service_name: str, ephilid_status: str) -> str:
    service_key = (service_name or "").strip().lower()
    status_key = (ephilid_status or "").strip().lower()
    if "delivered" in service_key or "delivery" in service_key:
        return "delivery"
    if "issued" in status_key and "paper form" in service_key:
        return "registration"
    return "registration"


def _build_source_key(record: dict, employee_name: str, service_name: str) -> str:
    parts = [
        _pick(record, "timestamp"),
        _pick(record, "transaction_reference_number__nid_card_number_29_digit_transaction_number__16_digit_nid_card_number"),
        _pick(record, "national_id_card_number_(former_philsys_card_number)"),
        employee_name,
        service_name,
        _pick(record, "first"),
        _pick(record, "middle"),
        _pick(record, "last"),
        _pick(record, "suffix"),
    ]
    raw = "|".join((part or "").strip() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_payload(payload_text: str | dict | None) -> dict:
    if not payload_text:
        return {}
    if isinstance(payload_text, dict):
        return payload_text
    try:
        return json.loads(payload_text)
    except json.JSONDecodeError:
        return {}


def _register_import_source(
    source_type: str,
    original_url: str,
    normalized_url: str,
    *,
    method: str | None = None,
    payload: str | None = None,
    last_status: str | None = None,
    last_error: str | None = None,
    rows_imported: int | None = None,
) -> None:
    try:
        save_import_source(
            source_type,
            original_url,
            normalized_url,
            method=method,
            payload=payload,
            last_status=last_status,
            last_error=last_error,
            rows_imported=rows_imported,
        )
    except Exception:
        pass


def import_from_csv_url(csv_url: str, original_url: str | None = None) -> int:
    source_type = "google_sheet"
    original_url = original_url or csv_url
    inserted = 0
    try:
        req = Request(csv_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=30) as response:
            content = response.read().decode("utf-8-sig")
        rows = csv.DictReader(io.StringIO(content))
        inserted = _persist_rows(rows, csv_url)
        _register_import_source(
            source_type,
            original_url,
            csv_url,
            last_status="ok",
            rows_imported=inserted,
        )
        return inserted
    except Exception as e:
        _register_import_source(
            source_type,
            original_url,
            csv_url,
            last_status="failed",
            last_error=str(e),
        )
        raise RuntimeError(
            f"Failed to import from Google Sheet URL: {e}"
        ) from e


def import_from_apps_script(
    url: str, method: str = "GET", payload: dict | None = None, original_url: str | None = None
) -> int:
    source_type = "apps_script"
    original_url = original_url or url
    method = method.upper()
    payload = payload or {}
    try:
        if method == "POST":
            response = requests.post(url, json=payload, timeout=30)
        else:
            response = requests.get(url, params=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            for key in ("data", "rows", "items", "records"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ValueError("Apps Script response must be a JSON array or an object containing a list.")
        inserted = _persist_rows(data, url)
        _register_import_source(
            source_type,
            original_url,
            url,
            method=method,
            payload=json.dumps(payload) if payload else None,
            last_status="ok",
            rows_imported=inserted,
        )
        return inserted
    except Exception as e:
        _register_import_source(
            source_type,
            original_url,
            url,
            method=method,
            payload=json.dumps(payload) if payload else None,
            last_status="failed",
            last_error=str(e),
        )
        raise RuntimeError(f"Apps Script import failed: {e}") from e


def _persist_rows(rows, source_ref: str) -> int:
    prepared_rows = []
    for raw in rows:
        if not raw:
            continue
        try:
            normalized = _normalize_record(raw, source_ref)
        except ValueError:
            continue
        employee_id = create_employee_if_missing(normalized)
        prepared_rows.append(
            {
                **normalized,
                "employee_id": employee_id,
            }
        )
    return bulk_insert_outputs(prepared_rows)
