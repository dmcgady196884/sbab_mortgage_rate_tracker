"""
Shared: redact likely secrets from git/gh output before it's embedded anywhere
more exposed than a console print -- pipeline_state.json (a long-retention
Actions artifact), the step summary, or the failure email.

Used by:
  - step 7 (commit/push/PR creation on a feature branch)
  - aleph_null.py's _commit_list_rates (pushes straight to main)

Narrow and lightweight by design, NOT a general-purpose secret scanner:
recognizes GitHub's own push-protection rejection shape (which deliberately
echoes the detected secret back to help locate it) and a short list of known
secret-token prefixes. A genuinely novel/custom secret format would not be
caught.
"""
import re

_PUSH_PROTECTION_MARKERS = ('gh013', 'push protection', 'push cannot contain secrets')
_SECRET_PATTERNS = [
    re.compile(r'gh[a-z]_[A-Za-z0-9]{20,}'),              # GitHub tokens: ghp_/gho_/ghu_/ghs_/ghr_
    re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),          # GitHub fine-grained PATs
    re.compile(r'AKIA[0-9A-Z]{16}'),                      # AWS access key IDs
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.DOTALL),
]


def redact_secrets(text):
    """Scrub likely secrets from git/gh output before it's embedded in a failure message."""
    if any(marker in text.lower() for marker in _PUSH_PROTECTION_MARKERS):
        return ("GitHub rejected this push because it detected a secret in the pushed "
                "content (message redacted). Check the Actions log directly, not this "
                "email, to see details and resolve it.")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub('[REDACTED]', text)
    return text


def combined_output(result):
    """stdout+stderr, redacted, for a failure message. Never stderr alone: git prints
    some diagnostics to stdout, not stderr -- e.g. "nothing to commit" -- so stderr-only
    would silently drop them. Shared by both call sites (step 7 and aleph_null.py's
    _commit_list_rates) so their failure messages can't silently drift apart."""
    parts = [p.strip() for p in (result.stdout, result.stderr) if p and p.strip()]
    return redact_secrets('\n'.join(parts) or '(no output)')
