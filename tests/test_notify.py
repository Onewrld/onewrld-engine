"""Email alerts, using a fake mail server so tests never send real email."""

import smtplib

import pytest

from onewrld import alerts, notify
from onewrld.errors import PermanentError, RetryableError


class FakeSMTP:
    """Stands in for Gmail. Records every message 'sent'."""
    sent: list = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


EMAIL_ENV = dict(ALERT_EMAIL="owner@example.com", SMTP_USER="bot@gmail.com",
                 SMTP_APP_PASSWORD="abcd efgh ijkl mnop")


def test_app_password_spaces_removed_and_hidden(make_settings):
    s = make_settings(**EMAIL_ENV)
    assert s.smtp_app_password == "abcdefghijklmnop"
    assert "abcdefgh" not in repr(s)  # secrets never appear in printouts
    assert s.email_configured


def test_send_email(make_settings, fake_smtp):
    notify.send_email(make_settings(**EMAIL_ENV), "subj", "body")
    assert fake_smtp.sent[0]["To"] == "owner@example.com"


def test_bad_login_is_permanent(make_settings, fake_smtp):
    fake_smtp.fail_with = smtplib.SMTPAuthenticationError(535, b"bad")
    with pytest.raises(PermanentError, match="app password"):
        notify.send_email(make_settings(**EMAIL_ENV), "s", "b")


def test_network_error_is_retryable(make_settings, fake_smtp):
    fake_smtp.fail_with = OSError("network down")
    with pytest.raises(RetryableError):
        notify.send_email(make_settings(**EMAIL_ENV), "s", "b")


def test_not_configured(make_settings):
    with pytest.raises(PermanentError, match="not configured"):
        notify.send_email(make_settings(), "s", "b")


# --- digest + caps (need a database) ----------------------------------------

@pytest.fixture
def email_db(db_settings, make_settings):
    from dataclasses import replace

    return replace(db_settings, alert_email="owner@example.com",
                   smtp_user="bot@gmail.com", smtp_app_password="x" * 16)


def test_alerts_bundled_into_one_email_and_marked(email_db, conn, fake_smtp):
    alerts.raise_alert(conn, "warn", "a", "first")
    alerts.raise_alert(conn, "critical", "b", "second")
    alerts.raise_alert(conn, "info", "c", "info is not emailed")
    assert notify.flush_alert_emails(email_db, conn) == "sent"
    assert len(fake_smtp.sent) == 1
    assert "CRITICAL" in fake_smtp.sent[0]["Subject"]
    assert notify.flush_alert_emails(email_db, conn) == "nothing"  # no repeats
    assert len(fake_smtp.sent) == 1


def test_hourly_cap(email_db, conn, fake_smtp):
    for i in range(notify.EMAILS_PER_HOUR + 1):
        alerts.raise_alert(conn, "warn", "x", f"alert {i}")
        outcome = notify.flush_alert_emails(email_db, conn)
    assert outcome == "rate_limited"
    assert len(fake_smtp.sent) == notify.EMAILS_PER_HOUR
    # the held-back alert is still waiting, not lost
    waiting = conn.execute(
        "SELECT count(*) AS n FROM alert WHERE emailed_at IS NULL").fetchone()["n"]
    assert waiting == 1


def test_failed_send_keeps_alert_for_next_time(email_db, conn, fake_smtp):
    alerts.raise_alert(conn, "warn", "x", "y")
    fake_smtp.fail_with = OSError("down")
    assert notify.flush_alert_emails(email_db, conn) == "failed"
    fake_smtp.fail_with = None
    assert notify.flush_alert_emails(email_db, conn) == "sent"


def test_worker_emails_dead_job_alert(email_db, conn, fake_smtp):
    from onewrld import jobs
    from onewrld.worker import run_worker

    jobs.enqueue(conn, "demo.fail", {"permanent": True}, "dies")
    run_worker(email_db, max_jobs=5, max_seconds=30)
    assert len(fake_smtp.sent) == 1
    assert "demo.fail" in fake_smtp.sent[0].get_content()


def test_phase1_check_passes(email_db, fake_smtp, monkeypatch, capsys):
    from onewrld import acceptance

    # The 'tests' step would re-run this whole suite inside itself; stub it here.
    monkeypatch.setattr(acceptance, "CHECKS", [
        c if c[0] != "tests" else ("tests", lambda s: (True, "stubbed"))
        for c in acceptance.CHECKS])
    assert acceptance.run(email_db), capsys.readouterr().out
    assert len(fake_smtp.sent) == 1
