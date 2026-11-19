"""SQLite data layer (stdlib ``sqlite3`` only - no ORM needed).

Schema
------
templates   - reusable phishing email templates (with trigger metadata)
recipients  - employees / targets (name, email, department, group)
campaigns   - a simulation run: template + sender + landing page + status
targets     - one row per (campaign, recipient): unique tracking token
events      - every tracked interaction: sent/opened/clicked/submitted/
              reported.  NEVER stores credential values - a "submitted"
              event records only that a submit happened, plus a timestamp.

All queries are parameterised.  Call ``init_db()`` once at startup and
``get_db()`` per request (Flask ``g``).
"""

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body_html   TEXT NOT NULL,
    triggers    TEXT NOT NULL,          -- comma-separated: urgency, authority, ...
    difficulty  TEXT NOT NULL DEFAULT 'medium',  -- easy / medium / hard
    red_flags   TEXT NOT NULL           -- newline-separated teaching points
);

CREATE TABLE IF NOT EXISTS recipients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    department  TEXT NOT NULL DEFAULT 'General',
    group_name  TEXT NOT NULL DEFAULT 'All Staff'
);

CREATE TABLE IF NOT EXISTS campaigns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    template_id     INTEGER NOT NULL REFERENCES templates(id),
    sender_name     TEXT NOT NULL,
    sender_email    TEXT NOT NULL,
    subject         TEXT,
    landing_type    TEXT NOT NULL DEFAULT 'login',  -- login | notice | download
    status          TEXT NOT NULL DEFAULT 'draft',  -- draft | sending | sent | completed
    authorized      INTEGER NOT NULL DEFAULT 0,     -- operator confirmed authorization
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    sent_at         TEXT
);

CREATE TABLE IF NOT EXISTS targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id),
    recipient_id    INTEGER NOT NULL REFERENCES recipients(id),
    token           TEXT NOT NULL UNIQUE,
    UNIQUE (campaign_id, recipient_id)
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id       INTEGER NOT NULL REFERENCES targets(id),
    event_type      TEXT NOT NULL,      -- sent | opened | clicked | submitted | reported
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ip_address      TEXT,
    user_agent      TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_target ON events(target_id);
CREATE INDEX IF NOT EXISTS idx_events_type   ON events(event_type);
"""


def get_db():
    """Return a per-request SQLite connection (row factory = dict-like)."""
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(exc=None):  # noqa: ARG001 - Flask teardown signature
    """Close the per-request connection, if one was opened."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app=None):
    """Create tables. Works with or without a Flask app context."""
    if app is not None:
        db_path = app.config["DATABASE"]
    else:
        from config import Config

        db_path = Config.DATABASE
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def connect_standalone(db_path):
    """Direct connection for seed.py / scripts (no Flask context)."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
