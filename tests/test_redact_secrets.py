"""
Unit tests for the shared redact_secrets() logic (no network, no files).

Used by both step 7 (commit/push/PR creation on a feature branch) and
aleph_null.py's _commit_list_rates (pushes straight to main) -- moved here from
tests/test_step7_real_path.py when the logic itself moved out of step 7 into
its own module, so both callers share one implementation instead of each
needing to remember to redact.

Run: pytest tests/test_redact_secrets.py -v
"""
from importlib import import_module

import pytest

from redact_secrets import redact_secrets, combined_output


def test_redact_secrets_replaces_a_push_protection_rejection_with_a_safe_summary():
    """GitHub's push protection deliberately echoes the detected secret back to help
    locate it -- that text must never reach pipeline_state.json/the step summary/the
    failure email verbatim."""
    raw = (
        "remote: error: GH013: Repository rule violations found for refs/heads/main.\n"
        "remote: - Push cannot contain secrets\n"
        "remote:    - GITHUB PERSONAL ACCESS TOKEN: ghp_1234567890abcdefghijklmnopqrstuvwxyz\n"
    )
    redacted = redact_secrets(raw)
    assert 'ghp_1234567890abcdefghijklmnopqrstuvwxyz' not in redacted
    assert 'GH013' not in redacted
    assert 'Check the Actions log' in redacted


@pytest.mark.parametrize('raw, secret', [
    ("Authorization: token ghp_1234567890abcdefghijklmnopqrstuvwxyz failed", 'ghp_1234567890abcdefghijklmnopqrstuvwxyz'),
    ("fine-grained token github_pat_11ABCDEFG0123456789_abcdefghij rejected", 'github_pat_11ABCDEFG0123456789_abcdefghij'),
    ("AWS key AKIAABCDEFGHIJKLMN12 is invalid", 'AKIAABCDEFGHIJKLMN12'),  # AKIA + 16 chars = AWS's real format
    ("key:\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\ndone",
     '-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----'),
], ids=['github-pat-classic', 'github-pat-fine-grained', 'aws-access-key', 'private-key-block'])
def test_redact_secrets_redacts_known_token_formats(raw, secret):
    """Defense-in-depth beyond push-protection specifically: known secret-token
    prefixes are redacted wherever they appear, with the surrounding text kept."""
    redacted = redact_secrets(raw)
    assert secret not in redacted
    assert '[REDACTED]' in redacted


def test_redact_secrets_leaves_ordinary_output_unchanged():
    """No false positives: normal git/gh error text is never redacted or rewritten."""
    raw = "error: failed to push some refs to 'https://github.com/someone/repo.git'"
    assert redact_secrets(raw) == raw


def test_combined_output_is_shared_by_both_callers():
    """
    Both step 7 and aleph_null.py's _commit_list_rates must use the SAME
    combined_output implementation, not independently-maintained copies that could
    silently drift apart -- this is exactly what happened once already (step 7 got
    its own _combined_output extracted while _commit_list_rates kept an inline copy),
    caught in review and fixed by moving it here.
    """
    step_7 = import_module('7_open_PR_with_updates_to_main')
    import aleph_null

    assert step_7.combined_output is combined_output
    assert aleph_null.combined_output is combined_output
