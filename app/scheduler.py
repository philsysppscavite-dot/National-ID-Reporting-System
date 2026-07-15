"""Background purge job for the 1-on-1 messenger, and the background sync
job for Data Entries -> Google Sheet.

Messages are supposed to disappear 10 hours after being sent, and the
repository already purges expired ones lazily every time someone opens or
polls a conversation. That's fine while people are actively using the app,
but if nobody touches Messages for a while, expired rows just sit there
until the next visit.

This module starts a lightweight daemon thread that calls the same purge
function on a fixed timer (every 15 minutes by default), so messages get
cleaned up on a real clock instead of only "on next click".

It also starts a second daemon thread for Data Entries: every Registration
/ Updating entry is always saved to the local SQLite database first (see
app/db.py + repository.save_data_entry), so field encoders never lose work
even if the Google Sheet is unreachable. This job periodically looks for
entries that haven't been sent to the configured TRN Logsheet yet and
retries sending them, so the sheet catches up on its own -- nobody has to
remember to click "Send to Sheet" once connectivity to Google is back.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading

logger = logging.getLogger(__name__)

# How often to sweep for expired direct messages. Doesn't need to be
# frequent -- messages live for 10 hours, so checking every 15 minutes
# means a message is removed no more than ~15 minutes after it expires.
PURGE_INTERVAL_SECONDS = 15 * 60

# How often to retry sending not-yet-sent Data Entries to the configured
# Google Sheet. Kept fairly frequent since the whole point is that a
# temporary outage (spotty signal, Google having a bad moment, etc.)
# resolves itself within a few minutes without anyone noticing.
DATA_ENTRY_SYNC_INTERVAL_SECONDS = 5 * 60


def _run_forever(app) -> None:
    stop_event = app.extensions["dm_purge_stop_event"]
    from .repository import purge_expired_direct_messages

    while not stop_event.wait(PURGE_INTERVAL_SECONDS):
        try:
            with app.app_context():
                purge_expired_direct_messages()
        except Exception:  # pragma: no cover - background job, log and keep going
            logger.exception("Direct message purge job failed")


def start_direct_message_purge_job(app) -> None:
    """Start the background purge thread for this app, once per process.

    Guards against Flask's debug-mode reloader starting the job twice (it
    forks a child process and only the child, marked by
    WERKZEUG_RUN_MAIN, should actually run background work), and against
    calling this twice on the same app.
    """
    if app.config.get("TESTING"):
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if app.extensions.get("dm_purge_thread") is not None:
        return

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_forever,
        args=(app,),
        name="direct-message-purge",
        daemon=True,
    )
    app.extensions["dm_purge_stop_event"] = stop_event
    app.extensions["dm_purge_thread"] = thread
    thread.start()

    atexit.register(stop_event.set)


def sync_pending_data_entries() -> int:
    """Send any not-yet-sent Data Entries to the configured TRN Logsheet.

    Safe to call any time: if nothing is pending, if no sheet URL is
    configured yet, or if the sheet is unreachable right now (no internet,
    Google having an outage, sheet not shared with the service account,
    etc.), this simply does nothing and leaves the rows exactly as they
    were -- they stay safely in the local database and get picked up again
    on the next scheduled run or the next manual "Send to Sheet" click.
    Returns the number of rows actually sent.
    """
    from .repository import fetch_settings, list_data_entries, mark_data_entries_sent_to_sheet
    from .services.export import ExportError, export_data_entries_to_sheet

    entries = list_data_entries({"sent_to_sheet": False})
    if not entries:
        return 0

    sheet_url = fetch_settings().get("trn_logsheet_url", "")
    if not sheet_url:
        return 0

    try:
        sent_count = export_data_entries_to_sheet(entries, sheet_url)
        mark_data_entries_sent_to_sheet([e["id"] for e in entries])
        return sent_count
    except ExportError as exc:
        logger.info("Data entry auto-sync skipped this round: %s", exc)
        return 0


def _run_data_entry_sync_forever(app) -> None:
    stop_event = app.extensions["data_entry_sync_stop_event"]

    while not stop_event.wait(DATA_ENTRY_SYNC_INTERVAL_SECONDS):
        try:
            with app.app_context():
                sent = sync_pending_data_entries()
                if sent:
                    logger.info("Data entry auto-sync sent %d row(s) to the TRN Logsheet.", sent)
        except Exception:  # pragma: no cover - background job, log and keep going
            logger.exception("Data entry auto-sync job failed")


def start_data_entry_sync_job(app) -> None:
    """Start the background Data Entry -> Google Sheet sync thread.

    Same guards as start_direct_message_purge_job above (skip under
    TESTING, avoid double-start under the debug reloader, avoid double-start
    on repeated calls).
    """
    if app.config.get("TESTING"):
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if app.extensions.get("data_entry_sync_thread") is not None:
        return

    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_data_entry_sync_forever,
        args=(app,),
        name="data-entry-sheet-sync",
        daemon=True,
    )
    app.extensions["data_entry_sync_stop_event"] = stop_event
    app.extensions["data_entry_sync_thread"] = thread
    thread.start()

    atexit.register(stop_event.set)
