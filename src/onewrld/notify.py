"""Notify: emails you about alerts.

SMTP is the standard protocol for sending email; we log in to Gmail's SMTP server with an
"app password" (a separate 16-letter password Google issues for one app, which you can
revoke any time without changing your real password).

Rules:
- Only 'warn' and 'critical' alerts are emailed. 'info' waits for the Monday memo.
- Alerts are bundled into one digest email, never one email per alert.
- Caps: at most EMAILS_PER_HOUR and EMAILS_PER_DAY. Over the cap, alerts simply wait and
  go out in the next allowed digest; none are lost.
- Alert emails are exempt from the kill switch and dry-run on purpose: they only ever go
  to you, and you need them most when things are stopped or broken.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import psycopg

from onewrld.config import Settings
from onewrld.errors import PermanentError, RetryableError
from onewrld.logging_setup import get_logger

log = get_logger(__name__)

EMAILS_PER_HOUR = 4
EMAILS_PER_DAY = 20
MAX_ALERTS_PER_EMAIL = 50
ADVISORY_LOCK_KEY = 0x0E1D_A1E7  # any fixed number; stops two workers emailing at once


def send_email(settings: Settings, subject: str, body: str) -> None:
    """Send one plain-text email to ALERT_EMAIL. Raises a classified error on failure."""
    if not settings.email_configured:
        raise PermanentError("Email not configured: set SMTP_USER, SMTP_APP_PASSWORD, "
                             "ALERT_EMAIL in .env (RUNBOOK section 9).")
    msg = EmailMessage()
    msg["From"] = settings.smtp_user
    msg["To"] = settings.alert_email
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20,
                              context=ssl.create_default_context()) as server:
            server.login(settings.smtp_user, settings.smtp_app_password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise PermanentError("Gmail rejected the login. Check SMTP_USER and that "
                             "SMTP_APP_PASSWORD is an app password (RUNBOOK section 9).") from None
    except (smtplib.SMTPException, OSError) as e:
        raise RetryableError(f"Could not send email ({type(e).__name__})") from None
    log.info(f"Email sent: {subject}", extra={"fields": {"event": "email_sent"}})


def _sent_counts(conn: psycopg.Connection) -> tuple[int, int]:
    row = conn.execute(
        """SELECT count(*) FILTER (WHERE sent_at > now() - interval '1 hour') AS hour,
                  count(*) FILTER (WHERE sent_at > now() - interval '1 day')  AS day
           FROM notification WHERE channel = 'email'"""
    ).fetchone()
    return row["hour"], row["day"]


def _record(conn: psycopg.Connection, subject: str, alert_ids: list[int]) -> None:
    with conn.transaction():
        conn.execute("INSERT INTO notification (subject, alert_ids) VALUES (%s, %s)",
                     (subject, alert_ids))
        if alert_ids:
            conn.execute("UPDATE alert SET emailed_at = now() WHERE id = ANY(%s)", (alert_ids,))


def _digest(rows: list[dict]) -> tuple[str, str]:
    worst = "critical" if any(r["severity"] == "critical" for r in rows) else "warn"
    subject = f"[ONEWRLD] {len(rows)} alert(s), worst: {worst.upper()}"
    lines = ["Alerts from the ONEWRLD system:", ""]
    for r in rows:
        lines.append(f"#{r['id']} [{r['severity'].upper()}] {r['source']}")
        lines.append(f"    {r['message']}")
        lines.append(f"    at {r['created_at']:%Y-%m-%d %H:%M} UTC")
    lines += ["", "To see open alerts:   python -m onewrld alerts",
              "To mark one as seen:  python -m onewrld ack <number>",
              "Emergency stop:       python -m onewrld kill \"reason\""]
    return subject, "\n".join(lines)


def flush_alert_emails(settings: Settings, conn: psycopg.Connection) -> str:
    """Email any un-emailed warn/critical alerts as one digest, within the caps.
    Returns: sent / nothing / not_configured / rate_limited / busy / failed."""
    if not settings.email_configured:
        return "not_configured"
    got = conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (ADVISORY_LOCK_KEY,)).fetchone()
    if not got["ok"]:
        return "busy"  # another worker is sending right now
    try:
        rows = conn.execute(
            """SELECT id, severity, source, message, created_at FROM alert
               WHERE emailed_at IS NULL AND severity IN ('warn', 'critical')
               ORDER BY created_at LIMIT %s""",
            (MAX_ALERTS_PER_EMAIL,),
        ).fetchall()
        if not rows:
            return "nothing"
        hour, day = _sent_counts(conn)
        if hour >= EMAILS_PER_HOUR or day >= EMAILS_PER_DAY:
            log.warning(f"Alert email held back by cap ({hour}/h, {day}/day); will retry")
            return "rate_limited"
        subject, body = _digest(rows)
        try:
            send_email(settings, subject, body)
        except (PermanentError, RetryableError) as e:
            log.error(f"Alert email failed: {e}")
            return "failed"
        _record(conn, subject, [r["id"] for r in rows])
        return "sent"
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))


def portal_waiting_email(settings: Settings, conn: psycopg.Connection, waiting: int,
                         new: int) -> str:
    """Tell the owner posts are waiting for approval. At most one of these an hour, and
    within the overall email caps. Returns: sent / not_configured / held / failed."""
    if not settings.email_configured or waiting <= 0:
        return "not_configured" if not settings.email_configured else "held"
    recent = conn.execute(
        """SELECT count(*) AS n FROM notification WHERE channel = 'email'
           AND subject LIKE '%%waiting for your approval%%' AND sent_at > now() - interval '1 hour'"""
    ).fetchone()["n"]
    hour, day = _sent_counts(conn)
    if recent or hour >= EMAILS_PER_HOUR or day >= EMAILS_PER_DAY:
        return "held"
    subject = f"[ONEWRLD] {waiting} post(s) waiting for your approval"
    body = "\n".join([
        f"{new} new post(s) were just edited from your team's uploads.",
        f"{waiting} in total are waiting on your Approve screen.", "",
        f"Open the portal: {settings.portal_url}" if settings.portal_url else
        "Open your portal (add PORTAL_URL to .env to get a link here).", "",
        "Approve them in bulk; the system hands the versions out to your team by itself."])
    try:
        send_email(settings, subject, body)
    except (PermanentError, RetryableError) as e:
        log.warning(f"Waiting-posts email failed: {e}")
        return "failed"
    _record(conn, subject, [])
    return "sent"


def send_test_email(settings: Settings, conn: psycopg.Connection | None = None) -> None:
    subject = "[ONEWRLD] Test email: alerts are working"
    send_email(settings, subject,
               "If you can read this, the ONEWRLD system can reach you.\n"
               "Real alerts will look like this, bundled, at most "
               f"{EMAILS_PER_HOUR} per hour and {EMAILS_PER_DAY} per day.")
    if conn is not None:
        _record(conn, subject, [])
