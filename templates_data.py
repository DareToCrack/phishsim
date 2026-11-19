"""Built-in phishing email templates (educational simulations).

Every template supports three placeholders, replaced at send time:

* ``{{name}}``    - recipient's first name
* ``{{company}}`` - simulated organisation name
* ``{{link}}``    - unique tracked link for this recipient

``triggers`` describe the psychological levers the template uses - the
reporting engine uses them for the "why they clicked" analysis.
``red_flags`` are shown on the landing page to teach the recipient what
to look for next time.
"""

TEMPLATES = [
    {
        "name": "Password Reset (IT Helpdesk)",
        "category": "Credential Harvesting",
        "subject": "Action required: Your {{company}} password expires in 24 hours",
        "difficulty": "easy",
        "triggers": "urgency, authority",
        "red_flags": (
            "The sender domain is not your company's real IT domain.\n"
            "Real IT teams never ask you to reset a password via an email link.\n"
            "The 24-hour deadline is artificial urgency designed to rush you.\n"
            "Hovering over the link shows a URL that does not match the company site."
        ),
        "body_html": """<p>Hi {{name}},</p>
<p>This is an automated message from the {{company}} IT Helpdesk.</p>
<p>Your network password will <strong>expire in 24 hours</strong>. To avoid being
locked out of your email and VPN, please reset your password now using the
secure link below:</p>
<p><a href="{{link}}">Reset My Password</a></p>
<p>If you do not reset your password before the deadline, your account will be
temporarily suspended and you will need to visit the IT desk in person.</p>
<p>Thank you,<br>{{company}} IT Helpdesk</p>""",
    },
    {
        "name": "HR Policy Update",
        "category": "Credential Harvesting",
        "subject": "Updated Remote Work Policy - acknowledgement required by Friday",
        "difficulty": "medium",
        "triggers": "authority, curiosity",
        "red_flags": (
            "The email asks you to sign in to read a policy - HR policies are "
            "normally shared on the intranet, not behind a login link.\n"
            "The sender's display name says HR, but the actual address is external.\n"
            "A Friday deadline pressures you to click before checking."
        ),
        "body_html": """<p>Dear {{name}},</p>
<p>As part of our annual review, {{company}} has updated the Remote Work and
Device Usage Policy, effective immediately.</p>
<p>All employees must read the updated policy and acknowledge it by Friday.
Please review the document here:</p>
<p><a href="{{link}}">Review Updated Policy</a></p>
<p>Failure to acknowledge the policy may affect your remote-work eligibility.</p>
<p>Regards,<br>Human Resources, {{company}}</p>""",
    },
    {
        "name": "Invoice / Payment Request",
        "category": "Business Email Compromise",
        "subject": "Invoice #INV-8841 overdue - payment required",
        "difficulty": "medium",
        "triggers": "urgency, authority, fear",
        "red_flags": (
            "An unexpected invoice you were not expecting is a classic lure.\n"
            "The invoice number and vendor name do not match any real supplier.\n"
            "Threats of late fees or service suspension are designed to create panic.\n"
            "Always verify payment requests through a known phone number, not by replying."
        ),
        "body_html": """<p>Hello {{name}},</p>
<p>Our records show invoice <strong>#INV-8841 for $1,480.00</strong> is now
overdue. Please review the invoice and arrange payment to avoid late fees
and suspension of service.</p>
<p><a href="{{link}}">View Invoice &amp; Pay Now</a></p>
<p>If payment is not received within 48 hours, the account will be referred
to collections.</p>
<p>Accounts Receivable<br>Vendor Billing Services</p>""",
    },
    {
        "name": "Microsoft Teams Invite / Outlook Storage",
        "category": "Credential Harvesting",
        "subject": "Your Outlook mailbox is almost full - free up space now",
        "difficulty": "hard",
        "triggers": "fear, urgency",
        "red_flags": (
            "Microsoft never sends mailbox warnings with a sign-in button.\n"
            "The branding looks right, but the link domain is not microsoft.com.\n"
            "Storage warnings use fear of losing email to make you click fast.\n"
            "Check storage in the real Outlook app instead of clicking email links."
        ),
        "body_html": """<p>Hi {{name}},</p>
<p>Your {{company}} Outlook mailbox has reached <strong>98% of its storage
limit</strong>. You will stop receiving new email once it is full.</p>
<p>Free up space or increase your quota now:</p>
<p><a href="{{link}}">Manage Mailbox Storage</a></p>
<p>You are receiving this message because your mailbox is managed by
{{company}} IT.</p>
<p>Microsoft 365 Team</p>""",
    },
    {
        "name": "Package Delivery Notification",
        "category": "Malware / Credential Harvesting",
        "subject": "Your package could not be delivered - reschedule now",
        "difficulty": "easy",
        "triggers": "curiosity, urgency",
        "red_flags": (
            "You were not expecting a delivery - unsolicited delivery notices are a red flag.\n"
            "Legitimate couriers do not ask you to log in to reschedule.\n"
            "The tracking link goes to an unfamiliar domain, not the courier's site.\n"
            "Generic greeting ('Dear customer') instead of your name."
        ),
        "body_html": """<p>Dear Customer,</p>
<p>We attempted to deliver your package today but were unable to reach you.
Your parcel is being held at the local depot and will be returned to sender
in 3 days if not rescheduled.</p>
<p><a href="{{link}}">Track &amp; Reschedule Delivery</a></p>
<p>Tracking ID: TRK-77120419<br>FastPost Couriers</p>""",
    },
    {
        "name": "Security Alert / MFA Verification",
        "category": "Credential Harvesting",
        "subject": "Unusual sign-in detected - verify your account now",
        "difficulty": "hard",
        "triggers": "fear, authority, urgency",
        "red_flags": (
            "The alert claims a sign-in from a location you do not recognise - "
            "but real alerts come from the app, not an email login link.\n"
            "The 'Verify' button does not lead to your company's real login page.\n"
            "Fear of account compromise is used to bypass your normal caution.\n"
            "Always open the security app yourself instead of clicking alert links."
        ),
        "body_html": """<p>Hi {{name}},</p>
<p>We detected an unusual sign-in to your {{company}} account from a new
device in an unfamiliar location. For your protection, some features have
been temporarily limited.</p>
<p>Please verify that this was you and secure your account:</p>
<p><a href="{{link}}">Verify My Account</a></p>
<p>If this was not you, verify immediately to prevent unauthorized access.</p>
<p>{{company}} Security Team</p>""",
    },
]
