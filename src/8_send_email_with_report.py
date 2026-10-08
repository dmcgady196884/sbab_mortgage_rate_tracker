"""
Step 8: Send Email with Report (ALWAYS)

Sends email to registered addresses summarizing what happened. Content varies
based on email type flag set throughout the pipeline.

This step ALWAYS runs - it's the final step of both the light run and deep run.

INPUTS:
    - email_type from step 5a (may be overwritten to "catastrophic_failure" by 6j)
    - PR URL from step 7 (if deep run succeeded, else None)
    - list_rate_changes from step 2 (if any)
    - break_lines_changed from step 6i (None unless a deep run actually
      happened -- see below)

OUTPUTS:
    - Email sent to registered addresses
    - No return value

I/O CONTRACT (from io_contracts.py):
    Input:  assert_email_type(email_type)
    Output: N/A (side effect: email sent)

EMAIL TYPES AND CONTENT:
    "no_change":
        Subject: SBAB Monitor - No Changes
        Body: Brief "all quiet" message, date of check

    "list_rate_change":
        Subject: SBAB Monitor - List Rate Change Detected
        Body: Which maturities changed, old vs new rates, delta in BPs

    "deep_run_started":
        Subject: SBAB Monitor - Discount Structure Changed (PR Opened)
        Body: Link to PR, summary of structural changes detected

    "catastrophic_failure":
        Subject: SBAB Monitor - ALERT: Validation Failed
        Body: What went wrong, needs manual investigation

    "pipeline_failed":
        Subject: SBAB Monitor - CRITICAL: Pipeline Failed
        Body: If a deep run had started: trigger reason, the error, where it crashed, and
              that main was not updated (same content as the old deep-run-only alert).
              Otherwise (crash before any deep run -- e.g. step 1's API assertion, a light-
              run scraper failure, the maturity-change bookkeeping): a general "pipeline
              crashed before completing" message with the error and where it crashed.
              Either way: link to the failed Actions run; attachments as they currently
              exist (may be stale if the crash was before this run regenerated them)

    "maturity_change":
        Subject: SBAB Monitor - Maturity Change — Deep Run Completed
        Body: Which maturities added/removed, deep run outcome, PR link

REGISTERED EMAIL ADDRESSES:
    Stored in config (not in code). See notify.py for implementation.

CONTEXT:
    - This is the FINAL step of the pipeline (both light and deep runs)
    - Runs regardless of what happened earlier
    - If deep run failed validation, email_type will be "catastrophic_failure"
"""
import json
import os
from datetime import date
from pathlib import Path

from io_contracts import assert_email_type, data_dir, CURRENT_DISCOUNT_SURFACE_PNG
from notify import send_email


def send_email_with_report(email_type, pr_url=None, list_rate_changes=None, is_test=False, force_shallow_diagnostics=None, rate_dp=2, maturity_changes=None, failure_reason=None, trigger_reason=None, failure_location=None, break_lines_changed=None):
    """
    Send email report based on pipeline outcome.

    Args:
        email_type: One of 'no_change', 'list_rate_change', 'deep_run_started',
                    'catastrophic_failure', 'maturity_change', 'pipeline_failed'
        pr_url: GitHub PR URL (if deep run succeeded)
        list_rate_changes: Dict of maturity changes (if list rates changed)
        is_test: If True, prepend "🧪 TEST EMAIL:" to subject
        force_shallow_diagnostics: If set, append diagnostic text to email body
        rate_dp: Decimal places detected in rate data (2 = integer BPs, 3+ = sub-BP)
        maturity_changes: Dict with 'added' and 'removed' lists (if maturities changed)
        failure_reason: Error text (if the pipeline crashed)
        trigger_reason: Why a deep run was triggered, if one had started before the
                        pipeline crashed (absent for a pure light-run/bookkeeping crash)
        failure_location: file:line in function where it crashed (if the pipeline crashed)
        break_lines_changed: bool from step 6i (None unless a deep run happened) --
                             whether this deep run's break lines differ from what was
                             previously on file

    Returns:
        bool: True if email sent successfully
    """
    assert_email_type(email_type)

    today_str = date.today().strftime('%Y%m%d')
    viz_dir = data_dir() / 'visualizations'

    # Build subject and body based on email type
    if email_type == 'no_change':
        subject = f"✓ [SBAB Daily Check] No changes - {today_str}"
        body = f"""SBAB Rate Monitor - Daily Check
Date: {today_str}

STATUS: All Clear - No Changes Detected
==========================================

✓ Scraper ran successfully
✓ Analysis completed
✓ Discount surface structure: UNIFORM (all maturities use same discount pattern)
✓ Interest rate changes: NONE (all offered rates identical to the last recorded values)
✓ Structural changes: NONE (bin structure unchanged)

SBAB's pricing remains stable. You'll be notified immediately if anything changes.

---
Automated SBAB Rate Monitor
GitHub: https://github.com/dmcgady196884/sbab_mortgage_rate_tracker
"""
        attachments = []

    elif email_type == 'list_rate_change':
        assert list_rate_changes, "list_rate_change email but no changes data"
        subject = f"[SBAB Daily Check] List Rate Change - {today_str}"

        # Format list rate changes
        changes_text = []
        for maturity, change in list_rate_changes.items():
            delta_bps = (change['new'] - change['old']) * 100
            direction = "+" if delta_bps > 0 else ""
            changes_text.append(
                f"  {maturity}m: {change['old']:.{rate_dp}f}% -> {change['new']:.{rate_dp}f}% ({direction}{delta_bps:.0f} bps)"
            )
        changes_str = "\n".join(changes_text)

        body = f"""SBAB Rate Monitor - Daily Check
Date: {today_str}

STATUS: List Rate Change Detected
==================================

The following list rates have changed:

{changes_str}

Note: Discount surface structure is unchanged.
Only the base list rates have been updated.
list_rates.csv has been committed directly to main.

ATTACHED: List rate history plots and per-maturity detail for changed maturities.

---
Automated SBAB Rate Monitor
"""
        # Attach list rate history plots (A, B) + per-maturity plots for changed maturities (C)
        attachments = []
        if viz_dir.exists():
            for name in ['list_rate_history_full.png', 'list_rate_history_1yr.png']:
                path = viz_dir / name
                if path.exists():
                    attachments.append(path)
            for maturity in list_rate_changes:
                path = viz_dir / f'list_rate_history_{maturity}m.png'
                if path.exists():
                    attachments.append(path)

    elif email_type == 'deep_run_started':
        subject = f"[SBAB Daily Check] Discount Structure Changed - PR Opened - {today_str}"
        body = f"""SBAB Rate Monitor - Daily Check
Date: {today_str}

STATUS: Discount Structure Change Detected
==========================================

SBAB has changed their discount structure!

A deep scrape was triggered to discover the new boundaries.
Validation passed - the new structure has been captured.

Pull Request: {pr_url or '(URL not available)'}

Please review the PR and merge when ready.

ATTACHED: Current discount surface and pricing surfaces for all maturities.

---
Automated SBAB Rate Monitor
"""
        # Attach ALL visualizations (discount + pricing surfaces)
        attachments = _collect_all_visualizations(viz_dir)
        # Attach boundary configs used by the deep run
        # Attach boundary configs (minimal lives in data/, refined in src/)
        for yaml_path in [data_dir() / 'boundaries_minimal.yaml',
                          Path(__file__).parent / 'boundaries_refined.yaml']:
            if yaml_path.exists():
                attachments.append(yaml_path)

    elif email_type == 'catastrophic_failure':
        subject = f"[SBAB] CRITICAL: Validation Failed - {today_str}"
        body = f"""{'=' * 70}
CATASTROPHIC FAILURE - IMMEDIATE ATTENTION REQUIRED
{'=' * 70}

Date: {today_str}

WHAT HAPPENED
-------------
1. Daily light scrape detected a pricing anomaly
2. Deep scraper ran to discover new boundaries
3. Validation re-ran the light scrape with new boundaries
4. VALIDATION FAILED - prices are STILL inconsistent!

This means SBAB's pricing structure cannot be captured by our current approach.
Either their pricing has become more complex, or there's a bug in our detection.

ACTION REQUIRED
---------------
1. Check any PR created by the deep scraper (may be incomplete)
2. Manually investigate SBAB's current pricing structure
3. This requires manual intervention to resolve

---
This is an automated CRITICAL alert from the SBAB Rate Monitor.
"""
        # Attach whatever visualizations we have for debugging
        attachments = _collect_all_visualizations(viz_dir)
        # Attach boundary configs (minimal lives in data/, refined in src/)
        for yaml_path in [data_dir() / 'boundaries_minimal.yaml',
                          Path(__file__).parent / 'boundaries_refined.yaml']:
            if yaml_path.exists():
                attachments.append(yaml_path)

    elif email_type == 'pipeline_failed':
        if os.getenv('GITHUB_RUN_ID'):
            run_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        else:
            run_url = '(local run - see terminal output)'
        subject = f"[SBAB] CRITICAL: Pipeline Failed - {today_str}"

        if trigger_reason is not None:
            what_happened = f"""A pricing change was detected and the deep run started, but it did not finish.

  Trigger:  {trigger_reason}
  Failure:  {failure_reason or '(no details)'}
  Where:    {failure_location or '(unknown)'}

main has NOT been updated. Tomorrow's run will detect the same change and
repeat the deep scrape (~4000 API calls)."""
        else:
            # If list rates changed earlier in this same run, say so here rather than
            # blanket-claiming nothing was recorded -- the block below (shared with
            # every email type) is about to append those deltas to this same email,
            # and the two must not contradict each other.
            no_discount_change_note = (
                "A list rate change WAS recorded separately (see below); no discount-\n"
                "structure change was detected before the crash."
                if list_rate_changes else
                "No pricing change has been recorded."
            )
            what_happened = f"""The daily pipeline crashed before any deep run was triggered
(e.g. the scraper, a schema check, or list-rate/maturity bookkeeping).

  Failure:  {failure_reason or '(no details)'}
  Where:    {failure_location or '(unknown)'}

{no_discount_change_note} Tomorrow's scheduled run will try again."""

        body = f"""{'=' * 70}
PIPELINE FAILED
{'=' * 70}

Date: {today_str}

WHAT HAPPENED
-------------
{what_happened}

ACTION REQUIRED
---------------
Check the failed run's log: {run_url}

ATTACHED: whatever visualizations and boundary configs exist right now. If the
crash happened before this run regenerated them, these may be from an earlier day.

---
This is an automated CRITICAL alert from the SBAB Rate Monitor.
"""
        # Attach whatever exists at the point of failure (same set as the PR-opened email)
        attachments = _collect_all_visualizations(viz_dir)
        # Attach boundary configs (minimal lives in data/, refined in src/)
        for yaml_path in [data_dir() / 'boundaries_minimal.yaml',
                          Path(__file__).parent / 'boundaries_refined.yaml']:
            if yaml_path.exists():
                attachments.append(yaml_path)

    elif email_type == 'maturity_change':
        added = maturity_changes.get('added', []) if maturity_changes else []
        removed = maturity_changes.get('removed', []) if maturity_changes else []

        added_str = ", ".join(f"{m}m" for m in added) if added else "none"
        removed_str = ", ".join(f"{m}m" for m in removed) if removed else "none"

        subject = f"[SBAB] Detected Changes to SBAB's Maturity Portfolio — Deep Run Completed - {today_str}"
        body = f"""SBAB Rate Monitor - Daily Check
Date: {today_str}

STATUS: Detected Changes to SBAB's Maturity Portfolio — Deep Run Completed
============================================================================

SBAB has changed the set of available mortgage maturities!

  Added maturities:   {added_str}
  Removed maturities: {removed_str}

The pipeline automatically:
  1. Updated VALID_MATURITIES in io_contracts.py
  2. Migrated CSV columns for new maturities
  3. Ran a deep scrape to discover the new pricing structure
  4. Validated the new boundaries

Pull Request: {pr_url or '(URL not available)'}

Please review the PR and merge when ready.

ATTACHED: Current discount surface and pricing surfaces for all maturities.

---
Automated SBAB Rate Monitor
"""
        # Attach all visualizations + boundary configs (same as deep_run_started)
        attachments = _collect_all_visualizations(viz_dir)
        # Attach boundary configs (minimal lives in data/, refined in src/)
        for yaml_path in [data_dir() / 'boundaries_minimal.yaml',
                          Path(__file__).parent / 'boundaries_refined.yaml']:
            if yaml_path.exists():
                attachments.append(yaml_path)

    else:
        # Should not reach here due to assert_email_type
        raise ValueError(f"Unknown email_type: {email_type}")

    # Append list rate changes to ANY email type where they occurred
    # (the list_rate_change type already handles this in its main body,
    # but deep_run_started / catastrophic_failure / maturity_change would
    # otherwise silently drop the list rate info)
    if list_rate_changes and email_type != 'list_rate_change':
        changes_text = []
        for maturity, change in list_rate_changes.items():
            delta_bps = (change['new'] - change['old']) * 100
            direction = "+" if delta_bps > 0 else ""
            changes_text.append(
                f"  {maturity}m: {change['old']:.{rate_dp}f}% -> {change['new']:.{rate_dp}f}% ({direction}{delta_bps:.0f} bps)"
            )
        body += f"""
LIST RATE CHANGES (concurrent with above)
==========================================
{chr(10).join(changes_text)}
"""
        # Attach list rate history PNGs
        if viz_dir.exists():
            for name in ['list_rate_history_full.png', 'list_rate_history_1yr.png']:
                path = viz_dir / name
                if path.exists():
                    attachments.append(path)
            for maturity in list_rate_changes:
                path = viz_dir / f'list_rate_history_{maturity}m.png'
                if path.exists():
                    attachments.append(path)

    # Append break-line-structure signal to ANY email type following a deep
    # run -- whether SBAB restructured bin boundaries (not just shifted
    # values within existing ones).
    if break_lines_changed is not None:
        if break_lines_changed:
            body += """
BREAK LINES: CHANGED
=====================
This deep run discovered a different bin boundary structure than what was
previously on file (new or relocated break lines) -- not just a value
change within existing boundaries.
"""
        else:
            body += """
BREAK LINES: unchanged
=======================
This deep run rediscovered the exact same bin boundary structure already
on file -- only discount values changed, not the boundaries themselves.
"""

    # Flag a bin-boundary structure change at subject-line level -- significant
    # enough (SBAB restructured break lines, not just shifted values within
    # existing ones) to be visible without opening the email. Placed before
    # the test-mode wrapping below so DO NOT MERGE still wins outermost in
    # test runs, but this is still the first thing seen in production.
    if break_lines_changed:
        subject = f"⚠️ BREAK LINES CHANGED — {subject}"

    # Apply test mode prefix if needed
    if is_test:
        subject = f"🧪 TEST EMAIL: {subject}"

    # Add DO NOT MERGE warning for test runs
    if os.getenv('IS_TEST', '').lower() == 'true':
        subject = f"⚠️ DO NOT MERGE — TEST RUN: {subject}"
        body = f"""{'=' * 70}
⚠️  THIS IS A TEST RUN — DO NOT MERGE ANY PR  ⚠️
{'=' * 70}

{body}"""

    # Append force-shallow diagnostics if present
    if force_shallow_diagnostics:
        subject = subject.replace('No changes', 'No changes (SHALLOW FORCED)')
        body += f"""
{'=' * 70}
{force_shallow_diagnostics}
{'=' * 70}
"""

    # Flag sub-basis-point precision if detected
    if rate_dp > 2:
        body += f"""
NOTE: Sub-basis-point precision detected ({rate_dp} decimal places).
SBAB is quoting rates with finer granularity than integer basis points.
"""

    # Send the email
    return send_email(subject, body, attachments=attachments)


def _collect_all_visualizations(viz_dir):
    """
    Collect all visualization PNGs for email attachment.

    Returns both discount_surface and pricing_surface PNGs.
    (Git only tracks discount_surface; email includes everything.)
    """
    attachments = []

    if not viz_dir.exists():
        return attachments

    # Collect all PNG files (discount_surface + pricing_surface)
    for png_file in sorted(viz_dir.glob('*.png')):
        if png_file.name == CURRENT_DISCOUNT_SURFACE_PNG:
            continue  # duplicate of the dated current surface (kept for the README)
        attachments.append(png_file)

    return attachments


if __name__ == '__main__':
    # Read IS_TEST from environment (set by the workflow)
    is_test = os.getenv('IS_TEST', 'false').lower() == 'true'

    # Read pipeline state from JSON file (written by previous steps)
    state_file = Path(__file__).parent.parent / 'data' / 'pipeline_state.json'
    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
        email_type = state.get('email_type', 'no_change')
        pr_url = state.get('pr_url')
        list_rate_changes = state.get('list_rate_changes')
        rate_dp = state.get('rate_precision', 2)
        break_lines_changed = state.get('break_lines_changed')
    else:
        email_type = 'no_change'
        pr_url = None
        list_rate_changes = None
        rate_dp = 6  # absurd default — if this shows in an email, something is wrong
        break_lines_changed = None

    send_email_with_report(
        email_type, pr_url, list_rate_changes, is_test=is_test, rate_dp=rate_dp,
        break_lines_changed=break_lines_changed,
    )
