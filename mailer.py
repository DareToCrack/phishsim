"""Email sending for the Phishing Simulation Tool.

Two modes:

* **Dry-run (default, ``DRY_RUN=True``)** - messages are written as
  ``.eml`` files into ``outbox/`` and NEVER touch a mail server.
  Nothing leaves the machine.
* **Live (``DRY_RUN=False``)** - messages are sent via SMTP
  (``smtplib``).  Live sends are only allowed when the operator has
  ticked the authorization checkbox AND every recipient domain is on
  the ``ALLOWED_DOMAINS`` allowlist (enforced in ``app.py``).

Every message carries:
* ``X-Phishing-Simulation: true`` - identifies it as a simulation
* ``X-Simulation-ID`` - the campaign/target token, for tracing
* ``List-Unsubscribe`` - lets recipients opt out of future simulations
* a 1x1 tracking pixel (``/t/open/<token>.png``) for open detection
"""

import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

PIXEL_HTML = (
    '<img src="{base}/t/open/{token}.png" width="1" height="1" '
    'alt="" style="display:none">'
)


def render_body(template_body, name, company, link, base_url, token):
    """Fill placeholders and append the invisible open-tracking pixel."""
    first_name = (name or "there").split()[0]
    html = (
        template_body.replace("{{name}}", first_name)
        .replace("{{company}}", company)
        .replace("{{link}}", link)
    )
    return html + PIXEL_HTML.format(base=base_url, token=token)


def build_message(*, sender_name, sender_email, recipient_email, subject,
                  html_body, sim_id):
    """Build a MIME message with simulation-identifying headers."""
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg["X-Phishing-Simulation"] = "true"
    msg["X-Simulation-ID"] = sim_id
    msg["List-Unsubscribe"] = "<mailto:security-training@example.com?subject=unsubscribe>"
    msg.attach(MIMEText(html_body, "html"))
    return msg


def send_one(config, *, sender_name, sender_email, recipient_email,
             subject, html_body, sim_id, campaign_id):
    """Send one message, or write it to the dry-run outbox.

    Returns ``"dry-run"`` or ``"sent"``.
    """
    msg = build_message(
        sender_name=sender_name,
        sender_email=sender_email,
        recipient_email=recipient_email,
        subject=subject,
        html_body=html_body,
        sim_id=sim_id,
    )

    if config["DRY_RUN"]:
        outbox = Path(config["OUTBOX_DIR"])
        outbox.mkdir(parents=True, exist_ok=True)
        safe_email = recipient_email.replace("@", "_at_").replace(".", "_")
        path = outbox / f"campaign{campaign_id}_{safe_email}_{sim_id[:12]}.eml"
        path.write_text(msg.as_string(), encoding="utf-8")
        return "dry-run"

    # Live send via SMTP.
    with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PORT"], timeout=30) as smtp:
        if config["SMTP_USE_TLS"]:
            smtp.starttls()
        if config["SMTP_USER"]:
            smtp.login(config["SMTP_USER"], config["SMTP_PASS"])
        smtp.send_message(msg)
    return "sent"


def send_campaign(config, db, campaign, targets, template, *, delay=None):
    """Send a campaign to all targets. Returns (sent_count, mode).

    ``targets`` is a list of rows with recipient + token fields.
    A small delay between sends keeps behaviour polite and
    rate-limit friendly.
    """
    if delay is None:
        delay = config["SEND_DELAY_SECONDS"]

    sent = 0
    mode = "dry-run" if config["DRY_RUN"] else "sent"
    for target in targets:
        link = f"{config['BASE_URL']}/t/click/{target['token']}"
        html = render_body(
            template["body_html"],
            target["name"],
            config["COMPANY_NAME"],
            link,
            config["BASE_URL"],
            target["token"],
        )
        subject = template["subject"].replace(
            "{{company}}", config["COMPANY_NAME"]
        )
        if campaign["subject"]:
            subject = campaign["subject"]
        send_one(
            config,
            sender_name=campaign["sender_name"],
            sender_email=campaign["sender_email"],
            recipient_email=target["email"],
            subject=subject,
            html_body=html,
            sim_id=target["token"],
            campaign_id=campaign["id"],
        )
        db.execute(
            "INSERT INTO events (target_id, event_type) VALUES (?, 'sent')",
            (target["id"],),
        )
        sent += 1
        if delay:
            time.sleep(delay)
    db.commit()
    return sent, mode
