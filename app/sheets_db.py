"""Google Sheets-backed storage for Users and the NID Concern Matrix.

Why this exists
----------------
Users and the Matrix (NID concerns + their message threads) are plain
records with no heavy SQL aggregation behind them, so they're a good fit
for living in a Google Sheet that staff can also open and read directly.
(Employees / Outputs / Schedules / reports stay on SQLite -- see
DEPLOYMENT.md -- because that side of the app leans on real SQL joins and
aggregation that would be slow and complex to reimplement against a
spreadsheet.)

Setup
-----
1. Create a Google Cloud service account, enable the Google Sheets API for
   it, and download its JSON key.
2. Share the target spreadsheet with the service account's email address
   (found in the JSON key as "client_email") as an Editor.
3. Set environment variables:
     GOOGLE_SHEETS_CREDENTIALS_JSON  -- the full JSON key, as one line, OR
     GOOGLE_SHEETS_CREDENTIALS_FILE  -- a path to that JSON file on disk
     GOOGLE_SHEET_ID                 -- the spreadsheet ID (the long id in
                                         the sheet's URL between /d/ and
                                         /edit). Optional -- defaults to
                                         the sheet set up during initial
                                         development.
4. On startup, init_sheets() creates any missing tabs and header rows
   automatically (so a brand-new, empty spreadsheet gets its headers
   generated for you), and seeds a starter Administrator account into the
   Users tab if it's empty.

Design
------
- Each "table" is one worksheet tab, addressed by an integer `id` column
  this module manages (auto-incrementing per tab), so the rest of the app
  can keep treating rows the way it did with SQLite.
- A short in-memory cache avoids hitting the Sheets API on every read
  (dashboard loads, ticket lists, etc.); any write invalidates that tab's
  cache immediately so changes show up right away.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1
from werkzeug.security import generate_password_hash

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Falls back to the spreadsheet set up during initial development if
# GOOGLE_SHEET_ID isn't set. Safe to override per-deployment.
DEFAULT_SHEET_ID = "1C0tDol4AQL59ODPbsADUVEZaGwlB7DAPwE8Fwgi4Lxs"

# table name -> header row (also defines column order in the sheet)
TABLES: dict[str, list[str]] = {
    "Users": ["id", "username", "password_hash", "full_name", "role", "active", "created_at"],
    "NidConcerns": [
        "id", "date_reported", "city_municipality", "trn_or_ref_no", "concern_type",
        "description", "status", "reported_by", "reported_by_user_id", "remarks", "created_at",
    ],
    "ConcernMessages": ["id", "concern_id", "sender_id", "body", "created_at"],
}

_INT_COLUMNS = {"id", "concern_id", "sender_id", "reported_by_user_id"}
_BOOL_COLUMNS = {"active"}

_CACHE_TTL_SECONDS = 20

_lock = threading.RLock()
_client = None
_spreadsheet = None
_worksheets: dict[str, "gspread.Worksheet"] = {}
_cache: dict[str, tuple[float, list[dict]]] = {}


class SheetsNotConfigured(RuntimeError):
    """Raised when Sheets credentials/config are missing."""


def _credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if raw:
        info = json.loads(raw)
        return Credentials.from_service_account_info(info, scopes=_SCOPES)
    path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE")
    if path:
        return Credentials.from_service_account_file(path, scopes=_SCOPES)
    raise SheetsNotConfigured(
        "Google Sheets credentials not configured. Set GOOGLE_SHEETS_CREDENTIALS_JSON "
        "(the service account JSON key, as one line) or GOOGLE_SHEETS_CREDENTIALS_FILE "
        "(a path to that JSON file) as an environment variable, and share the target "
        "sheet with the service account's client_email as an Editor."
    )


def _get_spreadsheet():
    global _client, _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet
    _client = gspread.authorize(_credentials())
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID)
    _spreadsheet = _client.open_by_key(sheet_id)
    return _spreadsheet


def _get_worksheet(table: str):
    if table in _worksheets:
        return _worksheets[table]
    ss = _get_spreadsheet()
    headers = TABLES[table]
    try:
        ws = ss.worksheet(table)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=table, rows=200, cols=max(10, len(headers)))
        ws.append_row(headers, value_input_option="RAW")
        _worksheets[table] = ws
        return ws
    if not ws.row_values(1):
        # Blank tab (e.g. a brand-new spreadsheet) -- auto-generate the header row.
        ws.append_row(headers, value_input_option="RAW")
    _worksheets[table] = ws
    return ws


def init_sheets() -> None:
    """Call once at app startup: opens the spreadsheet, creates any missing
    tabs + header rows, and seeds a starter admin account if Users is empty."""
    with _lock:
        for table in TABLES:
            _get_worksheet(table)
        _seed_default_admin()


def _seed_default_admin() -> None:
    if get_all("Users", use_cache=False):
        return
    username = os.environ.get("APP_USERNAME", "admin")
    password = os.environ.get("APP_PASSWORD", "changeme")
    insert(
        "Users",
        {
            "username": username,
            "password_hash": generate_password_hash(password),
            "full_name": "Administrator",
            "role": "Administrator",
            "active": 1,
        },
    )


def _row_to_dict(headers: list[str], row: list[str]) -> dict:
    data = {h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)}
    for key in _INT_COLUMNS:
        if key in data and data[key] not in (None, ""):
            try:
                data[key] = int(data[key])
            except (TypeError, ValueError):
                pass
    for key in _BOOL_COLUMNS:
        if key in data:
            data[key] = 1 if str(data[key]).strip().lower() in ("1", "true", "yes") else 0
    return data


def _read_all(table: str, use_cache: bool = True) -> list[dict]:
    with _lock:
        if use_cache and table in _cache:
            ts, rows = _cache[table]
            if time.time() - ts < _CACHE_TTL_SECONDS:
                return rows
        ws = _get_worksheet(table)
        values = ws.get_all_values()
        headers = TABLES[table]
        rows = [_row_to_dict(headers, r) for r in values[1:]] if values else []
        _cache[table] = (time.time(), rows)
        return rows


def _invalidate(table: str) -> None:
    with _lock:
        _cache.pop(table, None)


def get_all(table: str, use_cache: bool = True) -> list[dict]:
    return [dict(row) for row in _read_all(table, use_cache=use_cache)]


def get_by_id(table: str, row_id) -> dict | None:
    if row_id in (None, ""):
        return None
    row_id = int(row_id)
    for row in _read_all(table):
        if row.get("id") == row_id:
            return dict(row)
    return None


def find(table: str, **filters) -> list[dict]:
    return [
        dict(row)
        for row in _read_all(table)
        if all(str(row.get(k, "")) == str(v) for k, v in filters.items())
    ]


def find_one(table: str, **filters) -> dict | None:
    matches = find(table, **filters)
    return matches[0] if matches else None


def _next_id(table: str) -> int:
    ids = [row["id"] for row in _read_all(table) if isinstance(row.get("id"), int)]
    return (max(ids) + 1) if ids else 1


def insert(table: str, values: dict) -> int:
    with _lock:
        headers = TABLES[table]
        new_id = _next_id(table)
        record = {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        record.update(values)
        record["id"] = new_id
        ws = _get_worksheet(table)
        ws.append_row([str(record.get(h, "")) for h in headers], value_input_option="RAW")
        _invalidate(table)
        return new_id


def update(table: str, row_id, values: dict) -> None:
    with _lock:
        ws = _get_worksheet(table)
        headers = TABLES[table]
        all_values = ws.get_all_values()
        row_id = int(row_id)
        for idx, raw_row in enumerate(all_values[1:], start=2):  # sheet row number (1 = header)
            row_dict = _row_to_dict(headers, raw_row)
            if row_dict.get("id") == row_id:
                row_dict.update(values)
                end_cell = rowcol_to_a1(idx, len(headers))
                ws.update(
                    f"A{idx}:{end_cell}",
                    [[str(row_dict.get(h, "")) for h in headers]],
                    value_input_option="RAW",
                )
                _invalidate(table)
                return
        raise ValueError(f"No row with id={row_id} in {table!r}")


def delete(table: str, row_id) -> None:
    with _lock:
        ws = _get_worksheet(table)
        headers = TABLES[table]
        all_values = ws.get_all_values()
        row_id = int(row_id)
        for idx, raw_row in enumerate(all_values[1:], start=2):
            row_dict = _row_to_dict(headers, raw_row)
            if row_dict.get("id") == row_id:
                ws.delete_rows(idx)
                _invalidate(table)
                return
