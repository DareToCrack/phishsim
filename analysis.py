"""Reporting analytics for the Phishing Simulation Tool.

* ``campaign_stats`` - funnel counts + rates + risk score.
* ``why_they_clicked`` - trigger, timing, device and department analysis.
* ``generate_suggestions`` - tailored, prioritised recommendations.

All functions take a ``sqlite3`` connection (and the campaign row where
needed) and return plain dicts/lists, so they are easy to test and to
serve as JSON.
"""

from collections import Counter, defaultdict
from datetime import datetime

# Time-to-click buckets, in seconds after the "sent" event.
TIME_BUCKETS = [
    ("< 1 min (impulse)", 0, 60),
    ("1-5 min", 60, 300),
    ("5-30 min", 300, 1800),
    ("30-60 min", 1800, 3600),
    ("> 1 hour", 3600, float("inf")),
]

TRIGGER_LABELS = {
    "urgency": "Urgency / deadline pressure",
    "authority": "Authority (IT / HR / boss impersonation)",
    "curiosity": "Curiosity",
    "reward": "Reward / incentive",
    "fear": "Fear / account loss",
}


def _parse(ts):
    """Parse SQLite's ``YYYY-MM-DD HH:MM:SS`` timestamps."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.fromisoformat(ts)


def _rate(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def campaign_stats(db, campaign_id):
    """Funnel counts, rates and a 0-100 risk score for one campaign."""
    row = db.execute(
        """
        SELECT
          COUNT(DISTINCT t.id) AS total,
          COUNT(DISTINCT CASE WHEN e.event_type='sent'      THEN t.id END) AS sent,
          COUNT(DISTINCT CASE WHEN e.event_type='opened'    THEN t.id END) AS opened,
          COUNT(DISTINCT CASE WHEN e.event_type='clicked'   THEN t.id END) AS clicked,
          COUNT(DISTINCT CASE WHEN e.event_type='submitted' THEN t.id END) AS submitted,
          COUNT(DISTINCT CASE WHEN e.event_type='reported'  THEN t.id END) AS reported
        FROM targets t
        LEFT JOIN events e ON e.target_id = t.id
        WHERE t.campaign_id = ?
        """,
        (campaign_id,),
    ).fetchone()
    stats = dict(row)
    sent = stats["sent"] or stats["total"]
    stats["open_rate"] = _rate(stats["opened"], sent)
    stats["click_rate"] = _rate(stats["clicked"], sent)
    stats["submit_rate"] = _rate(stats["submitted"], sent)
    stats["report_rate"] = _rate(stats["reported"], sent)
    # Risk score: clicks and (especially) credential submits raise risk;
    # reports lower it.  Clamped to 0-100.
    stats["risk_score"] = max(
        0,
        min(
            100,
            round(
                stats["click_rate"] * 0.6
                + stats["submit_rate"] * 1.5
                - stats["report_rate"] * 0.4
            ),
        ),
    )
    return stats


def overall_stats(db):
    """Dashboard-wide totals across all campaigns."""
    row = db.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM campaigns) AS campaigns,
          (SELECT COUNT(*) FROM recipients) AS recipients,
          COUNT(DISTINCT t.id) AS total,
          COUNT(DISTINCT CASE WHEN e.event_type='sent'      THEN t.id END) AS sent,
          COUNT(DISTINCT CASE WHEN e.event_type='opened'    THEN t.id END) AS opened,
          COUNT(DISTINCT CASE WHEN e.event_type='clicked'   THEN t.id END) AS clicked,
          COUNT(DISTINCT CASE WHEN e.event_type='submitted' THEN t.id END) AS submitted,
          COUNT(DISTINCT CASE WHEN e.event_type='reported'  THEN t.id END) AS reported
        FROM targets t
        LEFT JOIN events e ON e.target_id = t.id
        """
    ).fetchone()
    stats = dict(row)
    sent = stats["sent"] or stats["total"]
    stats["open_rate"] = _rate(stats["opened"], sent)
    stats["click_rate"] = _rate(stats["clicked"], sent)
    stats["submit_rate"] = _rate(stats["submitted"], sent)
    stats["report_rate"] = _rate(stats["reported"], sent)
    stats["risk_score"] = max(
        0,
        min(
            100,
            round(
                stats["click_rate"] * 0.6
                + stats["submit_rate"] * 1.5
                - stats["report_rate"] * 0.4
            ),
        ),
    )
    return stats


def _device_from_ua(user_agent):
    """Rough device classification from a User-Agent string."""
    ua = (user_agent or "").lower()
    if "iphone" in ua or "android" in ua and "mobile" in ua:
        return "Mobile"
    if "ipad" in ua or "tablet" in ua:
        return "Tablet"
    if "windows" in ua or "macintosh" in ua or "linux" in ua:
        return "Desktop"
    return "Unknown"


def why_they_clicked(db, campaign_id):
    """Explain *why* people clicked: triggers, timing, device, department.

    Returns a dict with:
    * ``triggers`` - the psychological levers this campaign's template used
    * ``time_to_click`` - bucketed seconds between send and first click
    * ``devices`` - click counts by device class
    * ``by_department`` - per-department sent/clicked/submitted/reported
    * ``repeat_clickers`` - recipients who clicked in 2+ campaigns
    """
    template = db.execute(
        """
        SELECT t.triggers, t.name FROM templates t
        JOIN campaigns c ON c.template_id = t.id
        WHERE c.id = ?
        """,
        (campaign_id,),
    ).fetchone()
    triggers = []
    if template:
        triggers = [
            TRIGGER_LABELS.get(t.strip(), t.strip().title())
            for t in template["triggers"].split(",")
            if t.strip()
        ]

    rows = db.execute(
        """
        SELECT t.id AS target_id, r.name, r.email, r.department,
               e.event_type, e.created_at, e.user_agent
        FROM targets t
        JOIN recipients r ON r.id = t.recipient_id
        LEFT JOIN events e ON e.target_id = t.id
        WHERE t.campaign_id = ?
        ORDER BY t.id, e.created_at
        """,
        (campaign_id,),
    ).fetchall()

    sent_at, first_click, click_ua = {}, {}, {}
    dept = defaultdict(lambda: {"sent": 0, "clicked": 0, "submitted": 0, "reported": 0})
    for row in rows:
        d = dept[row["department"]]
        if row["event_type"] == "sent":
            d["sent"] += 1
            sent_at[row["target_id"]] = _parse(row["created_at"])
        elif row["event_type"] == "clicked":
            d["clicked"] += 1
            if row["target_id"] not in first_click:
                first_click[row["target_id"]] = _parse(row["created_at"])
                click_ua[row["target_id"]] = row["user_agent"]
        elif row["event_type"] == "submitted":
            d["submitted"] += 1
        elif row["event_type"] == "reported":
            d["reported"] += 1

    buckets = Counter()
    for target_id, clicked_at in first_click.items():
        sent = sent_at.get(target_id)
        if not sent or not clicked_at:
            continue
        seconds = max(0, (clicked_at - sent).total_seconds())
        for label, low, high in TIME_BUCKETS:
            if low <= seconds < high:
                buckets[label] += 1
                break
    time_to_click = [
        {"bucket": label, "count": buckets.get(label, 0)}
        for label, _, _ in TIME_BUCKETS
    ]

    devices = Counter(
        _device_from_ua(ua) for ua in click_ua.values()
    )
    devices = [{"device": k, "count": v} for k, v in devices.most_common()]

    by_department = []
    for name, counts in sorted(dept.items()):
        counts = dict(counts)
        counts["department"] = name
        counts["click_rate"] = _rate(counts["clicked"], counts["sent"])
        by_department.append(counts)
    by_department.sort(key=lambda d: d["click_rate"], reverse=True)

    repeat = db.execute(
        """
        SELECT r.name, r.email, COUNT(DISTINCT t.campaign_id) AS campaigns_clicked
        FROM targets t
        JOIN recipients r ON r.id = t.recipient_id
        JOIN events e ON e.target_id = t.id AND e.event_type = 'clicked'
        GROUP BY r.id
        HAVING campaigns_clicked >= 2
        ORDER BY campaigns_clicked DESC
        """
    ).fetchall()

    return {
        "template_name": template["name"] if template else "Unknown",
        "triggers": triggers,
        "time_to_click": time_to_click,
        "devices": devices,
        "by_department": by_department,
        "repeat_clickers": [dict(r) for r in repeat],
    }


def generate_suggestions(db, campaign_id, stats, analysis):
    """Produce tailored, prioritised recommendations (5-8 items).

    Each suggestion: ``priority`` (high/medium/low), ``title``,
    ``detail`` and ``audience`` (All / a department / repeat clickers).
    """
    suggestions = []

    def add(priority, title, detail, audience="All staff"):
        suggestions.append(
            {
                "priority": priority,
                "title": title,
                "detail": detail,
                "audience": audience,
            }
        )

    click_rate = stats["click_rate"]
    submit_rate = stats["submit_rate"]
    report_rate = stats["report_rate"]

    if click_rate > 20:
        add(
            "high",
            "Run mandatory phishing-awareness training",
            f"Click rate is {click_rate}% - well above the 10-15% industry "
            "benchmark for a first simulation. Schedule a 30-minute interactive "
            "session covering link inspection, sender verification and the "
            "report button, then re-test in 4 weeks.",
        )
    elif click_rate > 10:
        add(
            "medium",
            "Targeted refresher on link inspection",
            f"Click rate is {click_rate}%. A short refresher on hovering over "
            "links and checking sender domains should bring it under 10%.",
        )
    else:
        add(
            "low",
            "Maintain awareness with quarterly simulations",
            f"Click rate is a healthy {click_rate}%. Keep skills sharp with "
            "quarterly simulations using harder templates.",
        )

    if submit_rate > 0:
        add(
            "high",
            "Credential hygiene + MFA enforcement",
            f"{stats['submitted']} employee(s) entered credentials on the "
            "simulated page. Enforce MFA on all accounts, require password "
            "resets for affected users, and run a credential-phishing module.",
        )

    if report_rate < 10:
        add(
            "high",
            "Teach and promote the Report button",
            f"Only {report_rate}% of recipients reported the email. Most "
            "phishing damage is prevented by fast reporting - demo the "
            "Report Phishing button and praise reporters publicly.",
        )
    elif report_rate < 25:
        add(
            "medium",
            "Reinforce reporting behaviour",
            f"Report rate is {report_rate}%. Recognise reporters in team "
            "updates and add reporting to onboarding checklists.",
        )

    impulse = next(
        (b["count"] for b in analysis["time_to_click"] if "impulse" in b["bucket"]),
        0,
    )
    if impulse:
        add(
            "medium",
            "Train the 'pause before you click' habit",
            f"{impulse} click(s) happened within 60 seconds of delivery - "
            "impulse clicks. Teach the 10-second rule: stop, check the sender "
            "and hover the link before acting on urgent emails.",
        )

    if "Urgency / deadline pressure" in analysis["triggers"] and click_rate > 10:
        add(
            "medium",
            "Add an urgency-spotting module",
            "This campaign used deadline pressure and it worked. Run a module "
            "on recognising manufactured urgency ('expires in 24 hours', "
            "'account suspended') as a phishing signal.",
        )

    if "Fear / account loss" in analysis["triggers"] and click_rate > 10:
        add(
            "medium",
            "Teach out-of-band verification for security alerts",
            "Fear-based alerts drove clicks. Train staff to verify security "
            "alerts by opening the app or site directly - never via an email link.",
        )

    mobile = next(
        (d["count"] for d in analysis["devices"] if d["device"] == "Mobile"), 0
    )
    if mobile:
        add(
            "medium",
            "Cover mobile phishing in training",
            f"{mobile} click(s) came from mobile devices, where sender and "
            "link details are harder to inspect. Include mobile-specific "
            "examples (long-press to preview links) in the next session.",
        )

    worst = analysis["by_department"][:1]
    if worst and worst[0]["click_rate"] > 15 and worst[0]["sent"] >= 2:
        add(
            "high",
            f"Department focus: {worst[0]['department']}",
            f"{worst[0]['department']} had the highest click rate at "
            f"{worst[0]['click_rate']}% ({worst[0]['clicked']}/"
            f"{worst[0]['sent']}). Run a department-specific session and "
            "consider a follow-up simulation for this team.",
            audience=worst[0]["department"],
        )

    if analysis["repeat_clickers"]:
        names = ", ".join(c["name"] for c in analysis["repeat_clickers"][:3])
        add(
            "high",
            "Coach repeat clickers 1:1",
            f"{len(analysis['repeat_clickers'])} employee(s) clicked in "
            f"multiple campaigns (e.g. {names}). Offer supportive 1:1 "
            "coaching - not punishment - plus a phishing-recognition quiz.",
            audience="Repeat clickers",
        )

    if len(suggestions) < 5:
        add(
            "low",
            "Share results transparently (no naming and shaming)",
            "Publish anonymised campaign results internally and celebrate "
            "improvement. Blame-free reporting culture raises future report rates.",
        )
    if len(suggestions) < 6:
        add(
            "low",
            "Vary templates and difficulty next time",
            "Rotate templates (invoice, delivery, MFA alert) and increase "
            "difficulty gradually so training stays realistic.",
        )

    order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: order[s["priority"]])
    return suggestions[:8]
