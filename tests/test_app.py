"""Flask test-client tests for the Phishing Simulation Tool.

Run:  python3 -m pytest tests/ -v
Uses a throwaway SQLite database per test session (tmp_path) and
dry-run mode, so no real email is ever sent.
"""

import csv
import io
import sqlite3

import pytest

from app import create_app, ensure_templates
from config import Config
from db import init_db


class TestConfig(Config):
    TESTING = True
    DRY_RUN = True
    ADMIN_USER = "admin"
    ADMIN_PASS = "changeme"
    SECRET_KEY = "test-secret"


def _seed_test_db(db_path):
    """2 recipients + 1 draft campaign with tokens token-aaa / token-bbb."""
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute(
        "INSERT INTO recipients (name, email, department) VALUES "
        "('Test User', 'test.user@example.com', 'Engineering'),"
        "('Second User', 'second.user@example.com', 'Finance')"
    )
    db.execute(
        """
        INSERT INTO campaigns (name, template_id, sender_name, sender_email)
        VALUES ('Test Campaign', 1, 'IT Helpdesk', 'it@example.com')
        """
    )
    campaign_id = db.execute(
        "SELECT id FROM campaigns WHERE name='Test Campaign'"
    ).fetchone()["id"]
    db.execute(
        "INSERT INTO targets (campaign_id, recipient_id, token) VALUES (?, 1, 'token-aaa')",
        (campaign_id,),
    )
    db.execute(
        "INSERT INTO targets (campaign_id, recipient_id, token) VALUES (?, 2, 'token-bbb')",
        (campaign_id,),
    )
    db.commit()
    db.close()


@pytest.fixture()
def app(tmp_path):
    """App with an isolated database + outbox, seeded with templates."""
    TestConfig.DATABASE = str(tmp_path / "test.db")
    TestConfig.OUTBOX_DIR = str(tmp_path / "outbox")
    application = create_app(TestConfig)
    init_db(application)
    ensure_templates(application)
    _seed_test_db(TestConfig.DATABASE)
    yield application


class DemoConfig(TestConfig):
    DEMO_MODE = True
    DRY_RUN = False  # deliberately wrong: create_app must force it True


@pytest.fixture()
def demo_app(tmp_path):
    """App with DEMO_MODE on (Vercel-like), isolated DB + outbox."""
    DemoConfig.DATABASE = str(tmp_path / "demo.db")
    DemoConfig.OUTBOX_DIR = str(tmp_path / "demo-outbox")
    application = create_app(DemoConfig)
    init_db(application)
    ensure_templates(application)
    _seed_test_db(DemoConfig.DATABASE)
    yield application


@pytest.fixture()
def demo_client(demo_app):
    return demo_app.test_client()


@pytest.fixture()
def demo_logged_in(demo_client):
    demo_client.post("/demo-login", follow_redirects=True)
    return demo_client


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def logged_in(client):
    client.post(
        "/login",
        data={"username": "admin", "password": "changeme"},
        follow_redirects=True,
    )
    return client


def _event_count(db_path, event_type):
    db = sqlite3.connect(db_path)
    n = db.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = ?", (event_type,)
    ).fetchone()[0]
    db.close()
    return n


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------
def test_login_required_redirects(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_wrong_password_rejected(client):
    resp = client.post(
        "/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


def test_dashboard_loads(logged_in):
    resp = logged_in.get("/")
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data
    assert b"DRY-RUN" in resp.data


# ----------------------------------------------------------------------
# Campaigns
# ----------------------------------------------------------------------
def test_campaign_create(logged_in, app):
    resp = logged_in.post(
        "/campaigns/new",
        data={
            "name": "New Test Campaign",
            "template_id": "2",
            "sender_name": "HR",
            "sender_email": "hr@example.com",
            "recipient_ids": ["1", "2"],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"New Test Campaign" in resp.data
    db = sqlite3.connect(app.config["DATABASE"])
    n = db.execute(
        "SELECT COUNT(*) FROM campaigns WHERE name='New Test Campaign'"
    ).fetchone()[0]
    assert n == 1


def test_send_requires_authorization(logged_in):
    resp = logged_in.post("/campaigns/1/send", follow_redirects=True)
    assert b"written authorization" in resp.data
    assert _event_count(logged_in.application.config["DATABASE"], "sent") == 0


def test_dry_run_send_writes_eml_and_logs_sent(logged_in, app, tmp_path):
    resp = logged_in.post(
        "/campaigns/1/send", data={"authorized": "yes"}, follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"DRY-RUN" in resp.data
    eml_files = list((tmp_path / "outbox").glob("*.eml"))
    assert len(eml_files) == 2  # one per target
    assert b"X-Phishing-Simulation" in eml_files[0].read_bytes()
    assert _event_count(app.config["DATABASE"], "sent") == 2


# ----------------------------------------------------------------------
# Tracking
# ----------------------------------------------------------------------
def test_click_logs_event_and_redirects_to_landing(client, app):
    resp = client.get("/t/click/token-aaa")
    assert resp.status_code == 302
    assert "/landing/token-aaa" in resp.headers["Location"]
    assert _event_count(app.config["DATABASE"], "clicked") == 1


def test_open_pixel_logs_event(client, app):
    resp = client.get("/t/open/token-aaa.png")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert _event_count(app.config["DATABASE"], "opened") == 1


def test_unknown_token_404(client):
    assert client.get("/t/click/nope").status_code == 404
    assert client.get("/landing/nope").status_code == 404


def test_report_endpoint_logs_event(client, app):
    resp = client.get("/t/report/token-aaa")
    assert resp.status_code == 200
    assert b"Thank you for reporting" in resp.data
    assert _event_count(app.config["DATABASE"], "reported") == 1


# ----------------------------------------------------------------------
# Landing page: education + never stores credentials
# ----------------------------------------------------------------------
def test_landing_page_shows_education(client):
    resp = client.get("/landing/token-aaa")
    assert resp.status_code == 200
    assert b"simulated phishing email" in resp.data
    assert b"Red flags" in resp.data
    assert b"nothing you typed was" in resp.data.lower()


def test_landing_submit_logs_event_but_stores_no_values(client, app):
    resp = client.post(
        "/landing/token-aaa",
        data={"email": "victim@example.com", "password": "SuperSecret123!"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _event_count(app.config["DATABASE"], "submitted") == 1
    # Prove the password value is nowhere in the database.
    db = sqlite3.connect(app.config["DATABASE"])
    dump = "\n".join(
        row[0] for row in db.execute("SELECT sql FROM sqlite_master") if row[0]
    )
    for table in ("events", "targets", "recipients", "campaigns"):
        for row in db.execute(f"SELECT * FROM {table}"):
            assert "SuperSecret123!" not in str(tuple(row))
            assert "victim@example.com" not in str(tuple(row)) or table == "recipients"
    db.close()
    assert "SuperSecret123!" not in dump


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------
def test_report_page_shows_stats(logged_in, client):
    client.get("/t/click/token-aaa")
    client.get("/t/open/token-bbb.png")
    resp = logged_in.get("/report/1")
    assert resp.status_code == 200
    assert b"Why they clicked" in resp.data
    assert b"Recommendations" in resp.data
    assert b"Per-recipient timeline" in resp.data


def test_csv_export(logged_in):
    resp = logged_in.get("/report/1/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == [
        "name", "email", "department", "sent_at", "opened_at",
        "clicked_at", "submitted_at", "reported_at",
    ]
    assert len(rows) == 3  # header + 2 recipients


def test_stats_api(logged_in):
    resp = logged_in.get("/api/campaigns/1/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    assert "click_rate" in data and "risk_score" in data


def test_stats_api_404(logged_in):
    assert logged_in.get("/api/campaigns/999/stats").status_code == 404


# ----------------------------------------------------------------------
# Security headers + CSP-safe templates
# ----------------------------------------------------------------------
def test_security_headers_present(logged_in):
    resp = logged_in.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "strict-origin-when-cross-origin" in resp.headers["Referrer-Policy"]
    csp = resp.headers["Content-Security-Policy"]
    assert "https://cdn.jsdelivr.net" in csp  # Chart.js CDN allowed
    script_src = [d for d in csp.split(";") if "script-src" in d][0]
    assert "unsafe-inline" not in script_src  # no inline scripts needed


def test_no_inline_scripts_charts_use_data_attributes(logged_in):
    resp = logged_in.get("/")
    assert resp.status_code == 200
    assert b"window.PHISHSIM" not in resp.data
    assert b"<script>" not in resp.data  # only <script src=...> tags
    assert b'id="funnelChart"' in resp.data
    assert b'data-sent="0"' in resp.data
    assert b"cdn.jsdelivr.net/npm/chart.js" in resp.data
    resp = logged_in.get("/report/1")
    assert resp.status_code == 200
    assert b"window.PHISHSIM" not in resp.data
    assert b"<script>" not in resp.data
    assert b'id="deviceChart"' in resp.data
    assert b"data-devices=" in resp.data


# ----------------------------------------------------------------------
# Demo mode (read-only public tour)
# ----------------------------------------------------------------------
def test_demo_login_disabled_by_default(client):
    assert client.post("/demo-login").status_code == 404


def test_demo_mode_forces_dry_run(demo_app):
    assert demo_app.config["DEMO_MODE"] is True
    assert demo_app.config["DRY_RUN"] is True  # forced despite DRY_RUN=False


def test_demo_login_and_read_only_views(demo_logged_in):
    resp = demo_logged_in.get("/")
    assert resp.status_code == 200
    assert b"DEMO MODE" in resp.data
    assert demo_logged_in.get("/campaigns").status_code == 200
    assert demo_logged_in.get("/campaigns/1").status_code == 200
    assert demo_logged_in.get("/report/1").status_code == 200
    assert demo_logged_in.get("/templates").status_code == 200
    assert demo_logged_in.get("/api/campaigns/1/stats").status_code == 200
    assert demo_logged_in.get("/report/1/export.csv").status_code == 200


def _count(demo_app, sql):
    db = sqlite3.connect(demo_app.config["DATABASE"])
    n = db.execute(sql).fetchone()[0]
    db.close()
    return n


def test_demo_cannot_create_campaign(demo_logged_in, demo_app):
    resp = demo_logged_in.post(
        "/campaigns/new",
        data={"name": "Hax", "template_id": "2", "sender_name": "X",
              "sender_email": "x@example.com", "recipient_ids": ["1"]},
        follow_redirects=True,
    )
    assert b"disabled in demo mode" in resp.data
    assert _count(demo_app, "SELECT COUNT(*) FROM campaigns") == 1


def test_demo_cannot_send_or_delete(demo_logged_in, demo_app):
    resp = demo_logged_in.post(
        "/campaigns/1/send", data={"authorized": "yes"}, follow_redirects=True)
    assert b"disabled in demo mode" in resp.data
    assert _event_count(demo_app.config["DATABASE"], "sent") == 0
    demo_logged_in.post("/campaigns/1/delete", follow_redirects=True)
    assert _count(demo_app, "SELECT COUNT(*) FROM campaigns") == 1


def test_demo_cannot_add_recipients(demo_logged_in, demo_app):
    demo_logged_in.post(
        "/recipients",
        data={"name": "Nope", "email": "nope@example.com",
              "department": "General"},
        follow_redirects=True,
    )
    assert _count(demo_app, "SELECT COUNT(*) FROM recipients") == 2


def test_demo_landing_submit_blocked(demo_logged_in, demo_app):
    resp = demo_logged_in.post(
        "/landing/token-aaa",
        data={"email": "victim@example.com", "password": "SuperSecret123!"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"disabled in the read-only demo" in resp.data
    assert _event_count(demo_app.config["DATABASE"], "submitted") == 0


def test_demo_mode_disables_sending_for_admin_too(demo_client, demo_app):
    demo_client.post(
        "/login", data={"username": "admin", "password": "changeme"},
        follow_redirects=True)
    resp = demo_client.post(
        "/campaigns/1/send", data={"authorized": "yes"}, follow_redirects=True)
    assert b"Sending is disabled in demo mode" in resp.data
    assert _event_count(demo_app.config["DATABASE"], "sent") == 0
