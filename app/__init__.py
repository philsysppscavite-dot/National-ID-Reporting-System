import os
from datetime import timedelta
from pathlib import Path

from flask import Flask

from .auth import register_auth
from .db import init_app as init_db_app
from .scheduler import start_data_entry_sync_job, start_direct_message_purge_job
from .sheets_db import init_sheets
from .views import register_routes


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    is_production = os.environ.get("FLASK_ENV") == "production"

    # INSTANCE_DIR lets you point everything (db, reports, uploads) at a
    # mounted persistent disk when deployed (e.g. Render/Railway) instead of
    # the ephemeral app folder, which is wiped on every redeploy/restart.
    # Locally / without the env var this falls back to the normal Flask
    # instance folder exactly like before.
    instance_dir = Path(os.environ.get("INSTANCE_DIR") or app.instance_path)
    database_path = Path(os.environ.get("DATABASE_PATH") or (instance_dir / "accomplishment.db"))

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-in-production"),
        DATABASE=database_path,
        REPORT_OUTPUT_DIR=instance_dir / "reports",
        UPLOAD_DIR=instance_dir / "uploads",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=is_production,
    )

    if is_production and app.config["SECRET_KEY"] == "change-this-in-production":
        raise RuntimeError(
            "Set a real SECRET_KEY environment variable before running in production."
        )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(instance_dir).mkdir(parents=True, exist_ok=True)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["REPORT_OUTPUT_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    init_db_app(app)
    init_sheets()
    register_routes(app)
    register_auth(app)
    start_direct_message_purge_job(app)
    start_data_entry_sync_job(app)
    return app
