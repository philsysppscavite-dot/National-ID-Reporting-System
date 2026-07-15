# Accomplishment Report Dashboard

A Flask dashboard for PSA field teams to log employee accomplishment data,
schedule registration events, and export the Daily Accomplishment Report (DAR)
and other reports in the official format.

## What's in this version

- **Per-user accounts with roles** — replaces the old single shared login.
  Roles are Administrator, Information Systems Analyst I, and User. The
  Administrator manages accounts from the new **Users** page. The very
  first login still uses APP_USERNAME / APP_PASSWORD (default `admin` /
  `changeme`) and is seeded as an Administrator — change that password and
  create real accounts right away.
- **NID Concern tickets** — logging a concern now requires a 29-digit
  TRN / Reference No., pulls "Reported By" automatically from whoever is
  logged in, and no longer asks for City / Municipality. Concern types are:
  Request ID not found, Unclickable, OSI Validate, Validate Packet, Manual
  Verification, Upload Packets, Biometric Verification/Authentication, and
  Demographic Verification/Authentication.
- **Ticket status progress bar** — each ticket shows a progress bar that
  advances as an Information Systems Analyst (or Administrator) updates its
  status (Open → In Progress → Escalated → Resolved). Only that role can
  change a ticket's status; the reporting user can only view it.
- **Ticket thread messaging** — every ticket has its own message thread
  between the reporting user and Information Systems Analyst / Administrator
  accounts, so status updates and questions stay attached to the ticket.
- **1-on-1 messenger** — under **Messages**, any user can pick a colleague
  and chat directly. Messages are permanently deleted 10 hours after they're
  sent (auto-purged on each read/send), so it's meant for short-lived,
  same-day coordination rather than a permanent record.
- Login screen — the dashboard is no longer open to anyone with the link.
- Modern UI (Inter typeface, refreshed layout) — same pages, same navigation.
- Daily Accomplishment Report export rebuilt to match the official PSA DAR
  template exactly: Province / City-Municipality / Month-Year header, daily
  captured + cumulative columns, per-service remarks breakdown, grand total,
  and Prepared by / Verified as correct by signature blocks.
- Fixed a data bug where "Daily Captured" and "Cumulative" only counted
  National ID Registration and silently ignored every other service type
  (TRN Retrieval, Authentication, etc.). Totals now reflect all activity.
- Fixed the DAR always showing "Cavite / Trece Martires City" even when the
  underlying records were for a different province or city — it now pulls
  the real values from your data.

## Local setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
python wsgi.py
```

Open `http://127.0.0.1:5000`. Default login is `admin` / `changeme` — change
this immediately (see Environment variables below).

## Environment variables

Copy `.env.example` to `.env` (or set these in your host's dashboard):

| Variable       | Purpose                                                        |
|----------------|------------------------------------------------------------------|
| `FLASK_ENV`    | Set to `production` when deployed live.                        |
| `SECRET_KEY`   | Random secret for signing session cookies. Required in production. |
| `APP_USERNAME` | Login username (default `admin`).                              |
| `APP_PASSWORD` | Login password (default `changeme` — **change before going live**). |

Generate a secret key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Data Entries: saved offline-first, synced to Google Sheets automatically

Every Registration / Updating entry (the **Data Entry** page) is saved to
the app's own local database the moment it's submitted — this always
works, even if there's no internet or Google Sheets is temporarily
unreachable, so nobody loses work.

Separately, a background job checks every ~5 minutes for entries that
haven't been sent to the configured **TRN Logsheet** Google Sheet yet, and
sends them automatically once the app can reach Google again. There's also
a **Send Report to Google Sheet** button on the Data Entry page if you want
an entry sent immediately instead of waiting for the next automatic run.
Each entry shows **Pending** until it's been sent, then **Sent**.

The target sheet is set from **Dashboard → Report Settings → TRN Logsheet
Google Sheet URL** (an admin can change it any time, no redeploy needed).
It must be shared as **Editor** with the same service account email used
for the Users/NidConcerns sheet (see `GOOGLE_SHEETS_SETUP.md`) — no
additional Google Cloud Console setup or new Render environment variables
are needed to point it at a different sheet.


## Deploying online

See `DEPLOYMENT.md` for a step-by-step guide to putting this on Render
(free tier, no credit card).

## Features

- Employee master list
- Employee output encoding and editing
- Schedule / deployment planner with calendar view
- City / Municipality record per month
- Signatory management (Prepared by / Verified as correct by), wired into
  both the DAR preview and every generated DAR (Excel and PDF)
- NID Concern Matrix on the dashboard — log and track concerns by type and
  status, with a live counts table
- Google Sheet CSV import
- Daily Accomplishment Report (DAR) — matches the official PSA template,
  exportable per employee as Excel, or for all employees at once as PDF
- Employee Output Summary report, per-employee monthly PDF, locator charts,
  city service summaries, and bulk ZIP export

## Import notes

Use a CSV export URL like:

```text
https://docs.google.com/spreadsheets/d/<sheet-id>/export?format=csv&gid=<gid>
```

The sheet must be shared as "Anyone with the link can view" or the import
will fail with a 401.

### Expected import fields

- Employee: `employee`, `employee_name`, `full_name`, `name`, `personnel`
- Code: `employee_code`, `code`, `employee_id`
- Date: `date`, `work_date`, `transaction_date`
- Category: `category`, `report_type`, `module`
- Activity: `activity_type`, `activity`, `service`
- Quantity: `quantity`, `qty`, `count`, `total`, `output`
- Remarks: `remarks`, `remark`, `notes`
- Location: `province`, `city_municipality`, `city`, `municipality`
