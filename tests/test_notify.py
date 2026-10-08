"""
Unit tests for notify.send_email's failure contract (no network, no real SMTP).

The pipeline treats a failed report email as a failed run (non-zero exit), so a real SMTP
error must propagate. Unconfigured credentials are different: that is the deliberate
"no email" mode (e.g. the workflow's send_email=false input) and returns False.

Run: pytest tests/test_notify.py -v
"""
import pytest

import notify


def test_smtp_failure_propagates(monkeypatch):
    monkeypatch.setattr(notify, 'SMTP_USER', 'user@example.com')
    monkeypatch.setattr(notify, 'SMTP_PASS', 'not-a-real-password')
    monkeypatch.setattr(notify, 'TO_EMAIL', ['recipient@example.com'])

    def unreachable(host, port):
        raise OSError('connection refused (simulated)')

    monkeypatch.setattr(notify.smtplib, 'SMTP', unreachable)
    with pytest.raises(OSError, match='connection refused'):
        notify.send_email('subject', 'body')


def test_missing_credentials_return_false(monkeypatch):
    monkeypatch.setattr(notify, 'SMTP_USER', None)
    monkeypatch.setattr(notify, 'SMTP_PASS', None)
    monkeypatch.setattr(notify, 'TO_EMAIL', [])
    assert notify.send_email('subject', 'body') is False
