"""Seed the database with demo data for local development / demos.

Creates (idempotently - safe to re-run):
* 6 built-in email templates (from templates_data.py)
* 12 demo employees across 4 departments
* 2 campaigns (1 sent with realistic events, 1 draft)
* realistic event history: opens, clicks, 1 credential submit,
  2 reports, with plausible timestamps and user agents

Run:  python3 seed.py
"""

import random
import secrets
from datetime import datetime, timedelta

from config import Config
from db import SCHEMA, connect_standalone
from templates_data import TEMPLATES

EMPLOYEES = [
    ("Aarav Sharma", "aarav.sharma@example.com", "Engineering", "All Staff"),
    ("Priya Nair", "priya.nair@example.com", "Engineering", "All Staff"),
    ("Rohan Mehta", "rohan.mehta@example.com", "Engineering", "All Staff"),
    ("Sneha Iyer", "sneha.iyer@example.com", "Finance", "All Staff"),
    ("Vikram Rao", "vikram.rao@example.com", "Finance", "All Staff"),
    ("Ananya Gupta", "ananya.gupta@example.com", "Finance", "All Staff"),
    ("Karan Patel", "karan.patel@example.com", "HR", "All Staff"),
    ("Divya Menon", "divya.menon@example.com", "HR", "All Staff"),
    ("Arjun Singh", "arjun.singh@example.com", "Sales", "All Staff"),
    ("Meera Joshi", "meera.joshi@example.com", "Sales", "All Staff"),
    ("Nikhil Verma", "nikhil.verma@example.com", "Sales", "All Staff"),
    ("Ishita Das", "ishita.das@example.com", "Engineering", "All Staff"),
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]

# event_type -> (delay after send in seconds, probability weight)
EVENT_PLAN = [
    # (name, opened?, clicked?, submitted?, reported?, click delay seconds)
    ("Aarav Sharma", True, True, False, False, 45),       # impulse click
    ("Priya Nair", True, False, False, True, None),       # reporter
    ("Rohan Mehta", True, True, True, False, 120),        # submitted creds
    ("Sneha Iyer", True, True, False, False, 2400),       # slow click
    ("Vikram Rao", True, False, False, False, None),
    ("Ananya Gupta", False, False, False, False, None),   # never opened
    ("Karan Patel", True, True, False, False, 50),        # impulse click
    ("Divya Menon", True, False, False, True, None),      # reporter
    ("Arjun Singh", True, False, False, False, None),
    ("Meera Joshi", True, True, False, False, 900),
    ("Nikhil Verma", False, False, False, False, None),
    ("Ishita Das", True, False, False, False, None),
]


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def seed_demo(db_path=None):
    """Seed the demo dataset (idempotent - safe to re-run).

    Creates the 6 templates, 12 demo employees, the sent "Q4 Password
    Reset Simulation" campaign with realistic events, and the draft
    "November MFA Security Alert" campaign.  Reuses the same logic for
    local ``python3 seed.py`` runs and for the Vercel deployment, where
    the /tmp database is ephemeral and must be re-seeded on cold start.
    Returns True if any campaign was newly created, else False.
    """
    random.seed(42)
    db_path = db_path or Config.DATABASE
    db = connect_standalone(db_path)
    db.executescript(SCHEMA)  # create tables on this exact database
    db.commit()
    created_any = False

    # --- Templates -----------------------------------------------------
    for tpl in TEMPLATES:
        db.execute(
            """
            INSERT OR IGNORE INTO templates
              (name, category, subject, body_html, triggers, difficulty, red_flags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tpl["name"], tpl["category"], tpl["subject"], tpl["body_html"],
             tpl["triggers"], tpl["difficulty"], tpl["red_flags"]),
        )

    # --- Recipients ----------------------------------------------------
    for name, email, dept, group in EMPLOYEES:
        db.execute(
            """
            INSERT OR IGNORE INTO recipients (name, email, department, group_name)
            VALUES (?, ?, ?, ?)
            """,
            (name, email, dept, group),
        )
    db.commit()

    recipients = {
        r["name"]: r["id"]
        for r in db.execute("SELECT id, name FROM recipients")
    }
    template_ids = {
        r["name"]: r["id"]
        for r in db.execute("SELECT id, name FROM templates")
    }

    # --- Campaign 1: sent, with realistic events -----------------------
    if not db.execute(
        "SELECT 1 FROM campaigns WHERE name = 'Q4 Password Reset Simulation'"
    ).fetchone():
        sent_base = datetime.now() - timedelta(days=2, hours=3)
        cur = db.execute(
            """
            INSERT INTO campaigns
              (name, template_id, sender_name, sender_email, subject,
               landing_type, status, authorized, created_at, sent_at)
            VALUES (?, ?, ?, ?, ?, 'login', 'sent', 1, ?, ?)
            """,
            (
                "Q4 Password Reset Simulation",
                template_ids["Password Reset (IT Helpdesk)"],
                "IT Helpdesk",
                "it-helpdesk@example.com",
                None,
                _fmt(sent_base - timedelta(hours=1)),
                _fmt(sent_base),
            ),
        )
        campaign_id = cur.lastrowid
        for name, opened, clicked, submitted, reported, click_delay in EVENT_PLAN:
            cur = db.execute(
                "INSERT INTO targets (campaign_id, recipient_id, token) VALUES (?, ?, ?)",
                (campaign_id, recipients[name], secrets.token_urlsafe(24)),
            )
            target_id = cur.lastrowid
            ua = random.choice(USER_AGENTS)
            ip = f"10.0.0.{random.randint(2, 250)}"
            db.execute(
                "INSERT INTO events (target_id, event_type, created_at, ip_address, user_agent)"
                " VALUES (?, 'sent', ?, ?, ?)",
                (target_id, _fmt(sent_base), ip, ua),
            )
            if opened:
                db.execute(
                    "INSERT INTO events (target_id, event_type, created_at, ip_address, user_agent)"
                    " VALUES (?, 'opened', ?, ?, ?)",
                    (target_id, _fmt(sent_base + timedelta(seconds=random.randint(30, 600))), ip, ua),
                )
            if clicked:
                db.execute(
                    "INSERT INTO events (target_id, event_type, created_at, ip_address, user_agent)"
                    " VALUES (?, 'clicked', ?, ?, ?)",
                    (target_id, _fmt(sent_base + timedelta(seconds=click_delay)), ip, ua),
                )
            if submitted:
                db.execute(
                    "INSERT INTO events (target_id, event_type, created_at, ip_address, user_agent)"
                    " VALUES (?, 'submitted', ?, ?, ?)",
                    (target_id, _fmt(sent_base + timedelta(seconds=click_delay + 90)), ip, ua),
                )
            if reported:
                db.execute(
                    "INSERT INTO events (target_id, event_type, created_at, ip_address, user_agent)"
                    " VALUES (?, 'reported', ?, ?, ?)",
                    (target_id, _fmt(sent_base + timedelta(seconds=random.randint(300, 3600))), ip, ua),
                )
        db.commit()
        created_any = True
        print("Seeded campaign: Q4 Password Reset Simulation (sent, 12 targets)")

    # --- Campaign 2: draft ---------------------------------------------
    if not db.execute(
        "SELECT 1 FROM campaigns WHERE name = 'November MFA Security Alert'"
    ).fetchone():
        cur = db.execute(
            """
            INSERT INTO campaigns
              (name, template_id, sender_name, sender_email, subject,
               landing_type, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'login', 'draft', ?)
            """,
            (
                "November MFA Security Alert",
                template_ids["Security Alert / MFA Verification"],
                "Security Team",
                "security@example.com",
                None,
                _fmt(datetime.now() - timedelta(hours=2)),
            ),
        )
        campaign_id = cur.lastrowid
        for name in ["Aarav Sharma", "Priya Nair", "Sneha Iyer", "Karan Patel",
                     "Arjun Singh", "Meera Joshi"]:
            db.execute(
                "INSERT INTO targets (campaign_id, recipient_id, token) VALUES (?, ?, ?)",
                (campaign_id, recipients[name], secrets.token_urlsafe(24)),
            )
        db.commit()
        created_any = True
        print("Seeded campaign: November MFA Security Alert (draft, 6 targets)")

    print("Seed complete.")
    print(f"Database: {db_path}")
    db.close()
    return created_any


def main():
    seed_demo()


if __name__ == "__main__":
    main()
