"""Background purge job for the 1-on-1 messenger.

Messages are supposed to disappear 10 hours after being sent, and the
repository already purges expired ones lazily every time someone opens or
polls a conversation. That's fine while people are actively using the app,
but if nobody touches Messages for a while, expired rows just sit there
until the next visit.

This module starts a lightweight daemon thread that calls the same purge
function on a fixed timer (every 15 minutes by default), so messages get
cleaned up on a real clock instead of only "on next click".
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
