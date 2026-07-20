# Sending email from bmk

`bmk send-email` and `bmk send-notification`, backed by btx-lib-mail.

### Email Sending

The application includes email sending capabilities via [btx-lib-mail](https://pypi.org/project/btx-lib-mail/), supporting both simple notifications and rich HTML emails with attachments.

#### Email Configuration

Configure email settings via environment variables, `.env` file, or configuration files:

**Environment Variables:**

Environment variables use the format: `<PREFIX>___<SECTION>__<KEY>=value`
- Triple underscore (`___`) separates PREFIX from SECTION
- Double underscore (`__`) separates SECTION from KEY

```bash
export BMK___EMAIL__SMTP_HOSTS="smtp.gmail.com:587,smtp.backup.com:587"
export BMK___EMAIL__FROM_ADDRESS="alerts@myapp.com"
export BMK___EMAIL__SMTP_USERNAME="your-email@gmail.com"
export BMK___EMAIL__SMTP_PASSWORD="your-app-password"
export BMK___EMAIL__USE_STARTTLS="true"
export BMK___EMAIL__TIMEOUT="60.0"
```

**Configuration File**:
```toml
[email]
smtp_hosts = ["smtp.gmail.com:587", "smtp.backup.com:587"]  # Fallback to backup if primary fails
from_address = "alerts@myapp.com"
smtp_username = "myuser@gmail.com"
smtp_password = "secret_password"  # Consider using environment variables for sensitive data
use_starttls = true
timeout = 60.0
```

**`.env` File:**
```bash
# Email configuration for local testing
BMK___EMAIL__SMTP_HOSTS=smtp.gmail.com:587
BMK___EMAIL__FROM_ADDRESS=noreply@example.com
```

#### Gmail Configuration Example

For Gmail, create an [App Password](https://support.google.com/accounts/answer/185833) instead of using your account password:

```bash
BMK___EMAIL__SMTP_HOSTS=smtp.gmail.com:587
BMK___EMAIL__FROM_ADDRESS=your-email@gmail.com
BMK___EMAIL__SMTP_USERNAME=your-email@gmail.com
BMK___EMAIL__SMTP_PASSWORD=your-16-char-app-password
```

#### Send Simple Email

```bash
# Send basic email to one recipient
bmk send-email \
    --to recipient@example.com \
    --subject "Test Email" \
    --body "Hello from bitranox!"

# Send to multiple recipients
bmk send-email \
    --to user1@example.com \
    --to user2@example.com \
    --subject "Team Update" \
    --body "Please review the latest changes"
```

#### Send HTML Email with Attachments

```bash
bmk send-email \
    --to recipient@example.com \
    --subject "Monthly Report" \
    --body "Please find the monthly report attached." \
    --body-html "<h1>Monthly Report</h1><p>See attached PDF for details.</p>" \
    --attachment report.pdf \
    --attachment data.csv
```

#### Send Notifications

For simple plain-text notifications, use the convenience command:

```bash
# Single recipient
bmk send-notification \
    --to ops@example.com \
    --subject "Deployment Success" \
    --message "Application deployed successfully to production at $(date)"

# Multiple recipients
bmk send-notification \
    --to admin1@example.com \
    --to admin2@example.com \
    --subject "System Alert" \
    --message "Database backup completed successfully"
```

#### Programmatic Email Usage

```python
from bmk.adapters.email.config import EmailConfig
from bmk.composition import send_email, send_notification

# Configure email
config = EmailConfig(
    smtp_hosts=["smtp.gmail.com:587"],
    from_address="alerts@myapp.com",
    smtp_username="myuser@gmail.com",
    smtp_password="app-password",
    timeout=60.0,
)

# Send simple email
send_email(
    config=config,
    recipients="recipient@example.com",
    subject="Test Email",
    body="Hello from Python!",
)

# Send email with HTML and attachments
from pathlib import Path
send_email(
    config=config,
    recipients=["user1@example.com", "user2@example.com"],
    subject="Report",
    body="See attached report",
    body_html="<h1>Report</h1><p>Details in attachment</p>",
    attachments=[Path("report.pdf")],
)

# Send notification
send_notification(
    config=config,
    recipients="ops@example.com",
    subject="Deployment Complete",
    message="Production deployment finished successfully",
)
```

#### Sending Without a Live SMTP Server

Both functions accept an optional `transport`, forwarded to `btx_lib_mail`. Leaving it `None`
(the default) uses the library's own SMTP transport, so normal callers need not pass it.

Supplying one replaces only the wire step: `btx_lib_mail` still composes the message, validates
recipients and attachments, and orchestrates per-host failover, then hands each `(host, recipient)`
pair to the transport. That makes it the way to exercise delivery in a test without a live server,
and the seam for an alternative transport.

```python
class RecordingTransport:
    """Accept every message and remember it, instead of opening a socket."""

    def __init__(self) -> None:
        self.deliveries: list[tuple[str, str, bytes]] = []

    def deliver(self, *, host, sender, recipient, message, delivery) -> None:
        message.seek(0)
        self.deliveries.append((host, recipient, message.read()))


recorder = RecordingTransport()
send_email(
    config=config,
    recipients="recipient@example.com",
    subject="Test Email",
    body="Hello from Python!",
    transport=recorder,
)
assert recorder.deliveries[0][1] == "recipient@example.com"
```

Raise an exception from `deliver` to simulate a host refusing the message; `btx_lib_mail` then
falls over to the next configured host, so failover is testable the same way.

Prefer this over patching `smtplib.SMTP`. That pins the library's private wire protocol and breaks
whenever it changes - which is exactly what happened when 1.5.0 moved to RFC 3030 BDAT framing.

#### Email Troubleshooting

**Connection Failures:**
- Verify SMTP hostname and port are correct
- Check firewall allows outbound connections on SMTP port
- Test connectivity: `telnet smtp.gmail.com 587`

**Authentication Errors:**
- For Gmail: Use App Password, not account password
- Ensure username/password are correct
- Check for 2FA requirements

**Emails Not Arriving:**
- Check recipient's spam folder
- Verify `from_address` is valid and not blacklisted
- Review SMTP server logs for delivery status

