"""Configuration for the Phishing Simulation Tool.

All sensitive / environment-specific settings come from environment
variables (or a local ``.env`` file).  The application is SAFE BY DEFAULT:

* ``DRY_RUN`` is True unless explicitly disabled, so no real email is
  ever sent until the operator opts in with real SMTP credentials.
* The admin password defaults to a well-known value and the UI warns
  loudly until it is changed via the environment.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Vercel serverless functions have a read-only filesystem except /tmp,
# so on Vercel the SQLite database and dry-run outbox live under /tmp.
# Local development defaults are unchanged.
ON_VERCEL = os.environ.get("VERCEL") == "1"


class Config:
    """Flask configuration object."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")

    # ------------------------------------------------------------------
    # Demo mode: when True, anyone can explore a read-only demo without
    # the admin password (see the /demo-login route).  Demo users cannot
    # create, send or delete campaigns, manage recipients, or submit the
    # fake login form.  Sending is disabled entirely in demo mode.
    # Default False; set DEMO_MODE=true on the public Vercel deployment.
    # ------------------------------------------------------------------
    DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() in ("1", "true", "yes")

    # ------------------------------------------------------------------
    # Database (SQLite - no external database required)
    # ------------------------------------------------------------------
    DATABASE = os.environ.get(
        "DATABASE_PATH",
        "/tmp/phishing_sim.db" if ON_VERCEL
        else str(BASE_DIR / "instance" / "phishing_sim.db"),
    )

    # ------------------------------------------------------------------
    # Safety: dry-run is the DEFAULT.  Set DRY_RUN=false in .env only
    # after written authorization to run a real simulation.
    # ------------------------------------------------------------------
    DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes")

    # Directory where dry-run emails are written as .eml files.
    OUTBOX_DIR = os.environ.get(
        "OUTBOX_DIR", "/tmp/outbox" if ON_VERCEL else str(BASE_DIR / "outbox")
    )

    # Public base URL used to build tracking links, e.g.
    # http://localhost:5000 during local demos.
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")

    # ------------------------------------------------------------------
    # SMTP (only used when DRY_RUN is False)
    # ------------------------------------------------------------------
    SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "1025"))  # MailHog default
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("SMTP_PASS", "")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "false").lower() in ("1", "true", "yes")
    SMTP_FROM = os.environ.get("SMTP_FROM", "security-training@example.com")

    # Seconds to wait between individual sends (rate limiting).
    SEND_DELAY_SECONDS = float(os.environ.get("SEND_DELAY_SECONDS", "0.5"))

    # ------------------------------------------------------------------
    # Authorization gate: simulations may only target allowlisted
    # domains.  Comma-separated, e.g. "example.com,example.org".
    # Empty = no real sends allowed at all.
    # ------------------------------------------------------------------
    ALLOWED_DOMAINS = [
        d.strip().lower()
        for d in os.environ.get("ALLOWED_DOMAINS", "").split(",")
        if d.strip()
    ]

    # ------------------------------------------------------------------
    # Admin login (change via environment before any real deployment)
    # ------------------------------------------------------------------
    ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
    ADMIN_PASS = os.environ.get("ADMIN_PASS", "changeme")

    # Simulated organisation name used in templates / landing pages.
    COMPANY_NAME = os.environ.get("COMPANY_NAME", "Acme Corp")
