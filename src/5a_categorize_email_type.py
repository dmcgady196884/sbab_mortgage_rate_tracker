"""
Step 5a: Categorize Email Type

Determines what kind of email to send based on pipeline state so far.
Sets initial email type flag that will be read by step 8.

NOTE: If step 6j detects catastrophic failure during validation, it will
OVERWRITE this flag to "catastrophic_failure". This step just sets the
initial state based on steps 2 and 4.

INPUTS:
    1. list_rate_changes from step 2 (dict or None)
    2. deep_run_signal from step 4 (dict with 'trigger_deep_run' bool)

OUTPUTS:
    - email_type: str, one of:
        - "no_change": list rates unchanged, discount surface unchanged
        - "list_rate_change": list rates changed (report which maturities, deltas)
        - "deep_run_started": discount surface changed, deep run triggered

I/O CONTRACT (from io_contracts.py):
    Input:  assert_list_rate_changes(list_rate_changes)
            assert_deep_run_signal(deep_run_signal)
    Output: assert_email_type(email_type)

DECISION LOGIC:
    if deep_run_signal['trigger_deep_run']:
        return "deep_run_started"
    elif list_rate_changes is not None:
        return "list_rate_change"
    else:
        return "no_change"

FUTURE IDEAS:
    - Could integrate Riksbank styrrantan history for context, e.g.:
      "SBAB lowered their 24-month list rate by 20 BPs today.
       This follows Riksbanken's 25 BP cut last week."
"""
from io_contracts import (
    assert_list_rate_changes,
    assert_deep_run_signal,
    assert_email_type,
)


def categorize_email_type(list_rate_changes, deep_run_signal):
    """
    Determine email type based on pipeline state.

    Args:
        list_rate_changes: from step 2 (dict or None)
        deep_run_signal: from step 4 (dict with 'trigger_deep_run' bool)

    Returns:
        email_type: "no_change", "list_rate_change", or "deep_run_started"
    """
    assert_list_rate_changes(list_rate_changes)
    assert_deep_run_signal(deep_run_signal)

    if deep_run_signal['trigger_deep_run']:
        email_type = "deep_run_started"
    elif list_rate_changes is not None:
        email_type = "list_rate_change"
    else:
        email_type = "no_change"

    assert_email_type(email_type)
    return email_type
