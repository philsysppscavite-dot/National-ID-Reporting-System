import os
import sqlite3
from pathlib import Path

from flask import current_app, g

# Roles available in the system.
ROLE_ADMIN = "Administrator"
ROLE_ISA = "Information Systems Analyst I"
ROLE_USER = "User"
ROLES = [ROLE_ADMIN, ROLE_ISA, ROLE_USER]

# Only these email addresses are permitted to self-register an account via
# the "Register Here" link on the login page. Anyone whose email is not on
# this list is turned away with a message to contact the administrator, and
# anyone on this list who already has an account is also told to contact the
# administrator instead of being allowed to create a duplicate.
ALLOWED_REGISTRATION_EMAILS = {
    "l.francisco.psa@gmail.com",
    "r.casil.psa@gmail.com",
    "c.alto.psa@gmail.com",
    "c.romuar.psa@gmail.com",
    "r.gener.psa@gmail.com",
    "r.simpelo.psa@gmail.com",
    "j.canales.psa@gmail.com",
    "j.estoque.psa@gmail.com",
    "l.bondame.psa@gmail.com",
    "j.ldelrosario.psa@gmail.com",
    "raypert.lawag.psa@gmail.com",
    "l.grencio22.psa@gmail.com",
    "n.agellon.psa@gmail.com",
    "m.kingking.psa@gmail.com",
    "j.masicap.psa@gmail.com",
    "r.lisondra.psa@gmail.com",
    "d.irlandez.psa@gmail.com",
    "n.baurile.psa@gmail.com",
    "j.avenido.psa@gmail.com",
    "jd.santos.psa@gmail.com",
    "r1.padilla.psa@gmail.com",
    "jc.ponciano.psa@gmail.com",
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_code TEXT UNIQUE,
    full_name TEXT NOT NULL,
    sex TEXT,
    position TEXT,
    province TEXT,
    city_municipality TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employee_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    work_date TEXT NOT NULL,
    category TEXT NOT NULL,
    activity_type TEXT,
    sex TEXT,
    source_key TEXT,
    quantity INTEGER NOT NULL DEFAULT 0,
    remarks TEXT,
    province TEXT,
    city_municipality TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS signatories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL DEFAULT 'general',
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    position TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS import_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    original_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    method TEXT,
    payload TEXT,
    last_check_at TEXT,
    last_status TEXT,
    last_error TEXT,
    rows_imported INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    label TEXT,
    created_by_user_id INTEGER,
    created_by_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, normalized_url)
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_date TEXT NOT NULL,
    city_municipality TEXT NOT NULL,
    assigned_rko_employee_id INTEGER,
    assigned_ra_employee_id INTEGER,
    event_place_activity TEXT,
    status TEXT NOT NULL DEFAULT 'Pending',
    vehicle TEXT NOT NULL DEFAULT 'PSA',
    needed_rko_count INTEGER NOT NULL DEFAULT 1,
    needed_ra_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (assigned_rko_employee_id) REFERENCES employees (id) ON DELETE SET NULL,
    FOREIGN KEY (assigned_ra_employee_id) REFERENCES employees (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS schedule_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (schedule_id) REFERENCES schedules (id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_outputs_employee_date
ON employee_outputs (employee_id, work_date);

CREATE INDEX IF NOT EXISTS idx_outputs_city_date
ON employee_outputs (city_municipality, work_date);

CREATE INDEX IF NOT EXISTS idx_schedules_date
ON schedules (schedule_date);

CREATE INDEX IF NOT EXISTS idx_schedule_assignments_date_role
ON schedule_assignments (schedule_id, role);

CREATE TABLE IF NOT EXISTS data_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporting_date TEXT NOT NULL,
    city_municipality TEXT,
    barangay TEXT,
    specific_location TEXT,
    type_of_rc TEXT,
    rko_employee_id INTEGER,
    applicant_first_name TEXT,
    applicant_middle_name TEXT,
    applicant_last_name TEXT,
    applicant_suffix TEXT,
    trn_or_pcn TEXT,
    age_category TEXT,
    service_availed TEXT,
    ephilid_status TEXT,
    ephilid_issued_date TEXT,
    digital_id_assistance TEXT,
    digital_id_generated TEXT,
    digital_id_issue_notes TEXT,
    dob_month TEXT,
    dob_day TEXT,
    dob_year TEXT,
    gender TEXT,
    old_trn TEXT,
    contact_number TEXT,
    overseas_registrant TEXT,
    gov_ayuda_programs TEXT,
    authenticated_status TEXT,
    created_by_user_id INTEGER,
    created_by_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rko_employee_id) REFERENCES employees (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_data_entries_date
ON data_entries (reporting_date);

CREATE INDEX IF NOT EXISTS idx_data_entries_city_date
ON data_entries (city_municipality, reporting_date);

-- Per-user "Entry Defaults": lets each RKO/user pre-fill and optionally
-- lock (auto-input, read-only) specific Data Entry fields for themselves,
-- e.g. their own name as RKO, today's date, their usual city/barangay.
-- One row per user_id. Whether a field is locked is entirely the user's
-- own choice (set from the "My Entry Defaults" page).
CREATE TABLE IF NOT EXISTS entry_defaults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    city_municipality TEXT,
    city_municipality_locked INTEGER NOT NULL DEFAULT 0,
    barangay TEXT,
    barangay_locked INTEGER NOT NULL DEFAULT 0,
    specific_location TEXT,
    specific_location_locked INTEGER NOT NULL DEFAULT 0,
    type_of_rc TEXT,
    type_of_rc_locked INTEGER NOT NULL DEFAULT 0,
    rko_employee_id INTEGER,
    rko_employee_id_locked INTEGER NOT NULL DEFAULT 0,
    reporting_date_mode TEXT NOT NULL DEFAULT 'blank',
    reporting_date_locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rko_employee_id) REFERENCES employees (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS direct_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_direct_messages_pair
ON direct_messages (sender_id, recipient_id, created_at);

CREATE INDEX IF NOT EXISTS idx_direct_messages_created
ON direct_messages (created_at);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        # WAL mode lets one process write while others read without locking
        # errors -- important once the app is deployed behind gunicorn with
        # more than one worker process talking to the same SQLite file.
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(_error=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(SCHEMA)
    _ensure_column(db, "employee_outputs", "sex", "TEXT")
    _ensure_column(db, "employee_outputs", "source_key", "TEXT")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_outputs_source_key ON employee_outputs (source_key)"
    )
    db.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
        ("organization_name", "PHILIPPINE STATISTICS AUTHORITY"),
    )
    db.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
        ("report_title", "Daily Accomplishment Report"),
    )
    _ensure_column(db, "schedules", "assigned_rko_employee_id", "INTEGER")
    _ensure_column(db, "schedules", "assigned_ra_employee_id", "INTEGER")
    _ensure_column(db, "schedules", "event_place_activity", "TEXT")
    _ensure_column(db, "schedules", "status", "TEXT NOT NULL DEFAULT 'Pending'")
    _ensure_column(db, "schedules", "vehicle", "TEXT NOT NULL DEFAULT 'PSA'")
    _ensure_column(db, "schedules", "needed_rko_count", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(db, "schedules", "needed_ra_count", "INTEGER NOT NULL DEFAULT 1")
    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_schedule_assignments_unique
        ON schedule_assignments (schedule_id, employee_id, role)
        """
    )
    _ensure_column(db, "import_sources", "is_active", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(db, "import_sources", "label", "TEXT")
    _ensure_column(db, "import_sources", "created_by_user_id", "INTEGER")
    _ensure_column(db, "import_sources", "created_by_name", "TEXT")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_outputs_source_ref ON employee_outputs (source_ref)"
    )
    _ensure_column(db, "data_entries", "created_by_user_id", "INTEGER")
    _ensure_column(db, "data_entries", "created_by_name", "TEXT")
    _ensure_column(db, "data_entries", "sent_to_sheet", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "data_entries", "sent_to_sheet_at", "TEXT")
    db.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
        (
            "trn_logsheet_url",
            "https://docs.google.com/spreadsheets/d/1_MjBiPft36kYqFI-23J3fMOdeihBeboDlNyHTB4FUYQ/edit?gid=2009676142#gid=2009676142",
        ),
    )
    db.commit()


def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
