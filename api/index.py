"""Vercel serverless entrypoint for PhishSim.

Vercel's Python runtime serves the top-level WSGI ``app`` defined here.
All routes are rewritten to this file by ``vercel.json``.

On Vercel the filesystem is read-only except /tmp, so ``config.py``
automatically points the SQLite database at ``/tmp/phishing_sim.db``
when the ``VERCEL`` env var is set.  Because /tmp is ephemeral, the
demo dataset is (re-)seeded on cold start when the database is empty,
so the public demo is never blank.  ``seed_demo`` is idempotent, so
re-seeding an existing database is a cheap no-op.

Production safety is enforced by environment variables (see README):
``DRY_RUN=true`` and ``DEMO_MODE=true`` — sending is disabled entirely
in demo mode, so the public deployment can never send email.
"""

import os
import sys

# Make the project root importable (api/ runs as its own module dir).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app, ensure_templates  # noqa: E402
from db import init_db  # noqa: E402
from seed import seed_demo  # noqa: E402

app = create_app()
init_db(app)
ensure_templates(app)

if os.environ.get("VERCEL") == "1":
    # Fresh /tmp on a cold start -> seed the demo dataset so the live
    # demo always has campaigns, events and reports to explore.
    seed_demo(app.config["DATABASE"])
