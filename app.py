"""Phishing Simulation Tool - Flask application.

AUTHORIZED USE ONLY: this tool generates simulated phishing emails for
employee security-awareness training.  It must only be used with written
authorization from the organisation being tested, and only against its
own employees / test accounts.

Safety guarantees built into this app:
* DRY_RUN is True by default - emails are written to ``outbox/`` as
  ``.eml`` files and ZERO real email is sent until SMTP is configured
  and the operator opts out of dry-run mode.
* Live sends require the operator to tick an authorization checkbox
  AND every recipient domain to be on the ALLOWED_DOMAINS allowlist.
* The simulated login page NEVER stores passwords or any submitted
  credential values - it records only that a submit event occurred.
* Every email carries X-Phishing-Simulation headers, and the landing
  page immediately reveals the simulation and teaches red flags.
"""

import csv
import io
import secrets
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    Response,
    session,
    url_for,
)

from analysis import (
    campaign_stats,
    generate_suggestions,
    overall_stats,
    why_they_clicked,
)
from config import Config
from db import close_db, get_db, init_db
from mailer import send_campaign
from templates_data import TEMPLATES

# 1x1 transparent PNG (for the open-tracking pixel).
PIXEL = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def create_app(config_class=Config):
    """Application factory (lets tests build an isolated app)."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    # Demo mode is read-only by design: sending is impossible, so
    # dry-run is forced on even if DRY_RUN=false was configured.
    if app.config.get("DEMO_MODE"):
        app.config["DRY_RUN"] = True
    app.teardown_appcontext(close_db)

    # ------------------------------------------------------------------
    # Security headers (applied to every response, including tracking
    # endpoints).  The Content-Security-Policy allows Chart.js from the
    # jsDelivr CDN and same-origin scripts/styles only - there are no
    # inline scripts or event handlers left in the templates (chart data
    # is passed via data-* attributes), so 'unsafe-inline' is NOT needed
    # for scripts.  style-src keeps 'unsafe-inline' only as a safety net
    # for browser/Chart.js injected styles.
    # ------------------------------------------------------------------
    @app.after_request
    def _security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------
    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    def admin_required(view):
        """Login + full admin (not a read-only demo session)."""
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login", next=request.path))
            if session.get("demo"):
                flash(
                    "That action is disabled in demo mode - this is a "
                    "read-only tour of the app.",
                    "error",
                )
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)

        return wrapped

    @app.before_request
    def _load_user():
        g.user = session.get("user")

    # ------------------------------------------------------------------
    # Public: login / logout
    # ------------------------------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = request.form.get("username", "")
            password = request.form.get("password", "")
            if (
                user == app.config["ADMIN_USER"]
                and password == app.config["ADMIN_PASS"]
            ):
                session["logged_in"] = True
                session["user"] = user
                session["demo"] = False
                return redirect(request.args.get("next") or url_for("dashboard"))
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/demo-login", methods=["POST"])
    def demo_login():
        """Read-only demo access (only when DEMO_MODE is enabled).

        Lets recruiters / visitors explore the dashboard, campaigns,
        reports and templates without the admin password.  The session
        is flagged as a demo session, so every write action is blocked
        by the admin_required guard.
        """
        if not app.config.get("DEMO_MODE"):
            abort(404)
        session["logged_in"] = True
        session["user"] = "demo"
        session["demo"] = True
        flash(
            "Welcome to the live demo - this is a read-only tour. "
            "Creating, sending and deleting are disabled.",
            "success",
        )
        return redirect(url_for("dashboard"))

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @app.route("/")
    @login_required
    def dashboard():
        db = get_db()
        stats = overall_stats(db)
        campaigns = db.execute(
            """
            SELECT c.*, t.name AS template_name,
                   (SELECT COUNT(*) FROM targets WHERE campaign_id = c.id) AS target_count
            FROM campaigns c JOIN templates t ON t.id = c.template_id
            ORDER BY c.created_at DESC LIMIT 5
            """
        ).fetchall()
        recent_events = db.execute(
            """
            SELECT e.event_type, e.created_at, r.name AS recipient_name,
                   c.name AS campaign_name
            FROM events e
            JOIN targets t ON t.id = e.target_id
            JOIN recipients r ON r.id = t.recipient_id
            JOIN campaigns c ON c.id = t.campaign_id
            WHERE e.event_type != 'sent'
            ORDER BY e.created_at DESC LIMIT 8
            """
        ).fetchall()
        return render_template(
            "dashboard.html",
            stats=stats,
            campaigns=campaigns,
            recent_events=recent_events,
            dry_run=app.config["DRY_RUN"],
            default_password=app.config["ADMIN_PASS"] == "changeme",
        )

    # ------------------------------------------------------------------
    # Campaigns: list / create / detail / send
    # ------------------------------------------------------------------
    @app.route("/campaigns")
    @login_required
    def campaigns():
        db = get_db()
        rows = db.execute(
            """
            SELECT c.*, t.name AS template_name,
                   (SELECT COUNT(*) FROM targets WHERE campaign_id = c.id) AS target_count
            FROM campaigns c JOIN templates t ON t.id = c.template_id
            ORDER BY c.created_at DESC
            """
        ).fetchall()
        return render_template("campaigns.html", campaigns=rows)

    @app.route("/campaigns/new", methods=["GET", "POST"])
    @admin_required
    def campaign_new():
        db = get_db()
        templates = db.execute("SELECT * FROM templates ORDER BY name").fetchall()
        recipients = db.execute(
            "SELECT * FROM recipients ORDER BY department, name"
        ).fetchall()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            template_id = request.form.get("template_id")
            sender_name = request.form.get("sender_name", "").strip()
            sender_email = request.form.get("sender_email", "").strip()
            subject = request.form.get("subject", "").strip()
            landing_type = request.form.get("landing_type", "login")
            recipient_ids = request.form.getlist("recipient_ids")
            if not (name and template_id and sender_name and sender_email):
                flash("Name, template, sender name and sender email are required.", "error")
            elif not recipient_ids:
                flash("Select at least one recipient.", "error")
            else:
                cur = db.execute(
                    """
                    INSERT INTO campaigns
                      (name, template_id, sender_name, sender_email, subject, landing_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, template_id, sender_name, sender_email,
                     subject or None, landing_type),
                )
                campaign_id = cur.lastrowid
                for rid in recipient_ids:
                    db.execute(
                        "INSERT INTO targets (campaign_id, recipient_id, token)"
                        " VALUES (?, ?, ?)",
                        (campaign_id, rid, secrets.token_urlsafe(24)),
                    )
                db.commit()
                flash(f"Campaign '{name}' created with {len(recipient_ids)} target(s).", "success")
                return redirect(url_for("campaign_detail", campaign_id=campaign_id))
        return render_template(
            "campaign_new.html", templates=templates, recipients=recipients
        )

    @app.route("/campaigns/<int:campaign_id>")
    @login_required
    def campaign_detail(campaign_id):
        db = get_db()
        campaign = db.execute(
            """
            SELECT c.*, t.name AS template_name, t.category, t.triggers,
                   t.difficulty
            FROM campaigns c JOIN templates t ON t.id = c.template_id
            WHERE c.id = ?
            """,
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            abort(404)
        stats = campaign_stats(db, campaign_id)
        targets = db.execute(
            """
            SELECT t.*, r.name, r.email, r.department,
                   GROUP_CONCAT(e.event_type) AS events
            FROM targets t
            JOIN recipients r ON r.id = t.recipient_id
            LEFT JOIN events e ON e.target_id = t.id
            WHERE t.campaign_id = ?
            GROUP BY t.id
            ORDER BY r.name
            """,
            (campaign_id,),
        ).fetchall()
        return render_template(
            "campaign_detail.html",
            campaign=campaign,
            stats=stats,
            targets=targets,
            dry_run=app.config["DRY_RUN"],
            allowed_domains=app.config["ALLOWED_DOMAINS"],
        )

    @app.route("/campaigns/<int:campaign_id>/send", methods=["POST"])
    @admin_required
    def campaign_send(campaign_id):
        # Hard guard: sending is disabled entirely in demo mode, even
        # for an admin session, so the public deployment can never send.
        if app.config.get("DEMO_MODE"):
            flash(
                "Sending is disabled in demo mode - this public deployment "
                "never sends email.",
                "error",
            )
            return redirect(url_for("campaign_detail", campaign_id=campaign_id))
        db = get_db()
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if campaign is None:
            abort(404)
        if campaign["status"] != "draft":
            flash("Only draft campaigns can be sent.", "error")
            return redirect(url_for("campaign_detail", campaign_id=campaign_id))

        # ---- Authorization gate -------------------------------------
        authorized = request.form.get("authorized") == "yes"
        if not authorized:
            flash(
                "You must confirm you have written authorization to run this "
                "simulation before sending.",
                "error",
            )
            return redirect(url_for("campaign_detail", campaign_id=campaign_id))

        targets = db.execute(
            """
            SELECT t.*, r.name, r.email, r.department
            FROM targets t JOIN recipients r ON r.id = t.recipient_id
            WHERE t.campaign_id = ?
            """,
            (campaign_id,),
        ).fetchall()
        template = db.execute(
            "SELECT * FROM templates WHERE id = ?", (campaign["template_id"],)
        ).fetchone()

        # Live sends additionally require every recipient domain allowlisted.
        if not app.config["DRY_RUN"]:
            allowed = set(app.config["ALLOWED_DOMAINS"])
            blocked = [
                t["email"] for t in targets
                if t["email"].rsplit("@", 1)[-1].lower() not in allowed
            ]
            if blocked:
                flash(
                    "Live send blocked: these recipients are outside the "
                    f"ALLOWED_DOMAINS allowlist: {', '.join(blocked)}",
                    "error",
                )
                return redirect(url_for("campaign_detail", campaign_id=campaign_id))

        db.execute(
            "UPDATE campaigns SET status='sending', authorized=1 WHERE id = ?",
            (campaign_id,),
        )
        db.commit()
        sent, mode = send_campaign(
            app.config, db, campaign, targets, template
        )
        db.execute(
            """
            UPDATE campaigns SET status='sent', sent_at=datetime('now')
            WHERE id = ?
            """,
            (campaign_id,),
        )
        db.commit()
        if mode == "dry-run":
            flash(
                f"DRY-RUN: {sent} email(s) written to outbox/ - no real email sent.",
                "success",
            )
        else:
            flash(f"Campaign sent to {sent} recipient(s).", "success")
        return redirect(url_for("campaign_detail", campaign_id=campaign_id))

    @app.route("/campaigns/<int:campaign_id>/delete", methods=["POST"])
    @admin_required
    def campaign_delete(campaign_id):
        db = get_db()
        db.execute(
            "DELETE FROM events WHERE target_id IN "
            "(SELECT id FROM targets WHERE campaign_id = ?)",
            (campaign_id,),
        )
        db.execute("DELETE FROM targets WHERE campaign_id = ?", (campaign_id,))
        db.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
        db.commit()
        flash("Campaign deleted.", "success")
        return redirect(url_for("campaigns"))

    # ------------------------------------------------------------------
    # Recipients (manual add + CSV upload)
    # ------------------------------------------------------------------
    @app.route("/recipients", methods=["GET", "POST"])
    @login_required
    def recipients():
        db = get_db()
        if request.method == "POST":
            if session.get("demo"):
                flash(
                    "That action is disabled in demo mode - this is a "
                    "read-only tour of the app.",
                    "error",
                )
                return redirect(url_for("recipients"))
            if "csv_file" in request.files and request.files["csv_file"].filename:
                text = request.files["csv_file"].read().decode("utf-8", "ignore")
                reader = csv.DictReader(io.StringIO(text))
                added = 0
                for row in reader:
                    email = (row.get("email") or "").strip().lower()
                    name = (row.get("name") or "").strip()
                    if not email or "@" not in email:
                        continue
                    try:
                        db.execute(
                            """
                            INSERT INTO recipients (name, email, department, group_name)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                name or email.split("@")[0],
                                email,
                                (row.get("department") or "General").strip(),
                                (row.get("group") or "All Staff").strip(),
                            ),
                        )
                        added += 1
                    except Exception:  # duplicate email - skip silently
                        continue
                db.commit()
                flash(f"Imported {added} recipient(s) from CSV.", "success")
            else:
                name = request.form.get("name", "").strip()
                email = request.form.get("email", "").strip().lower()
                department = request.form.get("department", "General").strip()
                if name and email and "@" in email:
                    try:
                        db.execute(
                            """
                            INSERT INTO recipients (name, email, department)
                            VALUES (?, ?, ?)
                            """,
                            (name, email, department),
                        )
                        db.commit()
                        flash(f"Added {name}.", "success")
                    except Exception:
                        flash("That email already exists.", "error")
                else:
                    flash("Name and a valid email are required.", "error")
            return redirect(url_for("recipients"))
        rows = db.execute(
            "SELECT * FROM recipients ORDER BY department, name"
        ).fetchall()
        return render_template("recipients.html", recipients=rows)

    # ------------------------------------------------------------------
    # Templates (read-only listing)
    # ------------------------------------------------------------------
    @app.route("/templates")
    @login_required
    def templates():
        db = get_db()
        rows = db.execute("SELECT * FROM templates ORDER BY name").fetchall()
        return render_template("templates.html", templates=rows)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    @app.route("/report/<int:campaign_id>")
    @login_required
    def report(campaign_id):
        db = get_db()
        campaign = db.execute(
            """
            SELECT c.*, t.name AS template_name, t.category
            FROM campaigns c JOIN templates t ON t.id = c.template_id
            WHERE c.id = ?
            """,
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            abort(404)
        stats = campaign_stats(db, campaign_id)
        analysis = why_they_clicked(db, campaign_id)
        suggestions = generate_suggestions(db, campaign_id, stats, analysis)

        dept_filter = request.args.get("department", "")
        status_filter = request.args.get("status", "")
        rows = db.execute(
            """
            SELECT t.id AS target_id, r.name, r.email, r.department,
                   MAX(CASE WHEN e.event_type='sent'      THEN e.created_at END) AS sent_at,
                   MAX(CASE WHEN e.event_type='opened'    THEN e.created_at END) AS opened_at,
                   MAX(CASE WHEN e.event_type='clicked'   THEN e.created_at END) AS clicked_at,
                   MAX(CASE WHEN e.event_type='submitted' THEN e.created_at END) AS submitted_at,
                   MAX(CASE WHEN e.event_type='reported'  THEN e.created_at END) AS reported_at
            FROM targets t
            JOIN recipients r ON r.id = t.recipient_id
            LEFT JOIN events e ON e.target_id = t.id
            WHERE t.campaign_id = ?
            GROUP BY t.id
            ORDER BY r.name
            """,
            (campaign_id,),
        ).fetchall()
        # Derive per-recipient status + time-to-click, then apply filters.
        table = []
        for row in rows:
            r = dict(row)
            if r["submitted_at"]:
                r["status"] = "submitted"
            elif r["reported_at"]:
                r["status"] = "reported"
            elif r["clicked_at"]:
                r["status"] = "clicked"
            elif r["opened_at"]:
                r["status"] = "opened"
            elif r["sent_at"]:
                r["status"] = "sent"
            else:
                r["status"] = "pending"
            r["time_to_click"] = None
            if r["sent_at"] and r["clicked_at"]:
                from datetime import datetime as _dt

                delta = _dt.strptime(r["clicked_at"], "%Y-%m-%d %H:%M:%S") - _dt.strptime(
                    r["sent_at"], "%Y-%m-%d %H:%M:%S"
                )
                r["time_to_click"] = int(delta.total_seconds())
            if dept_filter and r["department"] != dept_filter:
                continue
            if status_filter and r["status"] != status_filter:
                continue
            table.append(r)
        departments = sorted({r["department"] for r in rows})
        return render_template(
            "report.html",
            campaign=campaign,
            stats=stats,
            analysis=analysis,
            suggestions=suggestions,
            table=table,
            departments=departments,
            dept_filter=dept_filter,
            status_filter=status_filter,
        )

    @app.route("/report/<int:campaign_id>/export.csv")
    @login_required
    def report_export(campaign_id):
        db = get_db()
        rows = db.execute(
            """
            SELECT r.name, r.email, r.department,
                   MAX(CASE WHEN e.event_type='sent'      THEN e.created_at END) AS sent_at,
                   MAX(CASE WHEN e.event_type='opened'    THEN e.created_at END) AS opened_at,
                   MAX(CASE WHEN e.event_type='clicked'   THEN e.created_at END) AS clicked_at,
                   MAX(CASE WHEN e.event_type='submitted' THEN e.created_at END) AS submitted_at,
                   MAX(CASE WHEN e.event_type='reported'  THEN e.created_at END) AS reported_at
            FROM targets t
            JOIN recipients r ON r.id = t.recipient_id
            LEFT JOIN events e ON e.target_id = t.id
            WHERE t.campaign_id = ?
            GROUP BY t.id
            ORDER BY r.name
            """,
            (campaign_id,),
        ).fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["name", "email", "department", "sent_at", "opened_at",
             "clicked_at", "submitted_at", "reported_at"]
        )
        for row in rows:
            writer.writerow(
                [row["name"], row["email"], row["department"], row["sent_at"],
                 row["opened_at"], row["clicked_at"], row["submitted_at"],
                 row["reported_at"]]
            )
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition":
                    f"attachment; filename=campaign-{campaign_id}-report.csv"
            },
        )

    @app.route("/api/campaigns/<int:campaign_id>/stats")
    @login_required
    def api_campaign_stats(campaign_id):
        db = get_db()
        if db.execute(
            "SELECT 1 FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone() is None:
            return jsonify({"error": "campaign not found"}), 404
        return jsonify(campaign_stats(db, campaign_id))

    # ------------------------------------------------------------------
    # Tracking endpoints (public - hit from inside the simulated email)
    # ------------------------------------------------------------------
    def _target_by_token(token):
        return get_db().execute(
            "SELECT * FROM targets WHERE token = ?", (token,)
        ).fetchone()

    def _log_event(target_id, event_type):
        db = get_db()
        db.execute(
            """
            INSERT INTO events (target_id, event_type, ip_address, user_agent)
            VALUES (?, ?, ?, ?)
            """,
            (
                target_id,
                event_type,
                request.remote_addr,
                request.headers.get("User-Agent", "")[:255],
            ),
        )
        db.commit()

    @app.route("/t/open/<token>.png")
    def track_open(token):
        target = _target_by_token(token)
        if target:
            _log_event(target["id"], "opened")
        return Response(PIXEL, mimetype="image/png")

    @app.route("/t/click/<token>")
    def track_click(token):
        target = _target_by_token(token)
        if not target:
            abort(404)
        _log_event(target["id"], "clicked")
        return redirect(url_for("landing", token=token))

    @app.route("/t/report/<token>")
    def track_report(token):
        target = _target_by_token(token)
        if not target:
            abort(404)
        _log_event(target["id"], "reported")
        return render_template("reported.html")

    # ------------------------------------------------------------------
    # Landing page - immediately reveals the simulation and teaches.
    # The fake login form NEVER stores submitted values: on POST we
    # record only that a submit event happened (plus timestamp/IP/UA).
    # ------------------------------------------------------------------
    @app.route("/landing/<token>", methods=["GET", "POST"])
    def landing(token):
        db = get_db()
        target = db.execute(
            """
            SELECT t.*, r.name AS recipient_name, c.name AS campaign_name,
                   c.landing_type, tmp.name AS template_name,
                   tmp.red_flags, tmp.triggers
            FROM targets t
            JOIN recipients r ON r.id = t.recipient_id
            JOIN campaigns c ON c.id = t.campaign_id
            JOIN templates tmp ON tmp.id = c.template_id
            WHERE t.token = ?
            """,
            (token,),
        ).fetchone()
        if not target:
            abort(404)
        submitted = False
        demo_blocked = False
        if request.method == "POST":
            if session.get("demo"):
                # Read-only demo visitors explore the landing page but
                # cannot submit the fake login (and no event is logged).
                demo_blocked = True
            else:
                # SECURITY: deliberately discard ALL form values. We record
                # only that a submit occurred - never any credential or
                # password the user typed.  See _log_event: it stores no
                # form data at all.
                _log_event(target["id"], "submitted")
                submitted = True
        red_flags = [
            line for line in (target["red_flags"] or "").split("\n") if line.strip()
        ]
        return render_template(
            "landing.html",
            target=target,
            red_flags=red_flags,
            submitted=submitted,
            demo_blocked=demo_blocked,
            token=token,
            company=app.config["COMPANY_NAME"],
        )

    # ------------------------------------------------------------------
    # Context: dry-run flag + company name available in every template
    # ------------------------------------------------------------------
    @app.context_processor
    def inject_globals():
        return {
            "DRY_RUN": app.config["DRY_RUN"],
            "DEMO_MODE": app.config.get("DEMO_MODE", False),
            "IS_DEMO": bool(session.get("demo")),
            "COMPANY_NAME": app.config["COMPANY_NAME"],
        }

    return app


def ensure_templates(app):
    """Seed the 6 built-in templates if the table is empty."""
    with app.app_context():
        db = get_db()
        count = db.execute("SELECT COUNT(*) AS n FROM templates").fetchone()["n"]
        if count == 0:
            for tpl in TEMPLATES:
                db.execute(
                    """
                    INSERT INTO templates
                      (name, category, subject, body_html, triggers, difficulty, red_flags)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tpl["name"],
                        tpl["category"],
                        tpl["subject"],
                        tpl["body_html"],
                        tpl["triggers"],
                        tpl["difficulty"],
                        tpl["red_flags"],
                    ),
                )
            db.commit()


if __name__ == "__main__":
    app = create_app()
    init_db(app)
    ensure_templates(app)
    app.run(host="127.0.0.1", port=5000, debug=True)
