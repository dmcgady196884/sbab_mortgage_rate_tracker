"""
SBAB Rate Monitor - Pipeline Orchestrator (aleph_null)

This is the main entry point that orchestrates all pipeline steps.
Runs once daily via GitHub Action, or on-demand for dev/testing.

FLOW:
    Light Run (always):
        1  → scrape minimal grid
        2  → analyze list rates (updates list_rates.csv before 3a uses it)
        3a → convert to DataFrames (discount = list_rate - offered_rate)
        3b → create PNGs if needed
        4  → analyze shape (uniformity check)
        5a → categorize email type

    Deep Run (if step 4 triggers):
        5b → open feature branch
        6a → scrape refined grid
        6b → check list rates from deep scrape
        6c → extract rasterized discount surfaces
        6d → extract minimal break lines
        6e → make bins from break lines
        6f → close deprecated discount surfaces
        6g → create new discount surface rows
        6h → create all PNG visualizations
        6i → update boundaries_minimal.yaml
        6j → validate deep run
        7  → open PR (if validation passed)

    Always:
        8  → send email report

STATE MANAGEMENT:
    Pipeline state is passed between steps via function returns.
    Before step 8, state is written to pipeline_state.json for CLI invocation.

USAGE:
    python aleph_null.py                    # production run
    IS_TEST=true python aleph_null.py       # test mode (prefixes email subjects)
    python aleph_null.py --force-shallow    # suppress deep runs
"""
import json
import os
import subprocess
import sys
import traceback
from datetime import date
from pathlib import Path

# Add code directory to path for imports
CODE_DIR = Path(__file__).parent
sys.path.insert(0, str(CODE_DIR))

# Import step modules using importlib to handle numeric prefixes
from importlib import import_module
import pandas as pd
from io_contracts import (
    rate_precision, detect_maturity_changes, data_dir,
    update_maturities, update_valid_maturities_on_disk, VALID_MATURITIES,
    GIT_IDENTITY_NAME, GIT_IDENTITY_EMAIL,
)
from monitor_list_rate import handle_maturity_change_list_rates
from redact_secrets import combined_output

# Light run steps
step_1 = import_module('1_scraper_run_on_minimal_grid')
step_2 = import_module('2_analyze_list')
step_3a = import_module('3a_convert_csv_to_nice_pd_df')
step_3b = import_module('3b_create_discount_and_price_pngs')
step_4 = import_module('4_analyze_shape')
step_5a = import_module('5a_categorize_email_type')

# Deep run steps
step_5b = import_module('5b_open_FB_trigger_deep_if_needed')
step_6a = import_module('6a_scraper_run_on_refined_grid')
step_6b = import_module('6b_analyze_list')
step_6c = import_module('6c_extract_rasterized_disc_surface')
step_6d = import_module('6d_extract_minimal_break_lines')
step_6e = import_module('6e_make_bins_from_break_lines')
step_6f = import_module('6f_close_deprecated_disc_surfaces')
step_6g = import_module('6g_create_minimal_new_disc_surface')
step_6h = import_module('6h_create_all_png_visualizations')
step_6i = import_module('6i_update_boundaries_minimal')
step_6j = import_module('6j_validate_deep_run')
step_7 = import_module('7_open_PR_with_updates_to_main')

# Always run this final email notification step:
step_8 = import_module('8_send_email_with_report')


def _format_shallow_diagnostics(deep_run_signal):
    """Format diagnostic text for --force-shallow email."""
    reason = deep_run_signal['reason']
    details = deep_run_signal.get('details', [])

    lines = [
        "FORCE-SHALLOW MODE: Deep run was suppressed",
        f"Reason deep run would have triggered: {reason}",
        "",
        "Details:",
    ]

    if 'Non-uniformity' in reason:
        lines.append("  (ltv_bin, vol_bin, maturity_months)")
        for ltv, vol, mat in details:
            lines.append(f"  {ltv}, {vol}, {mat}m")
    else:
        dp = deep_run_signal.get('rate_precision', 2)
        lines.append("  ltv_bin | vol_bin | maturity | expected | actual | delta_bps")
        lines.append("  " + "-" * 70)
        for ltv, vol, mat, expected, actual in details:
            delta = (actual - expected) * 100
            sign = "+" if delta > 0 else ""
            lines.append(f"  {ltv} | {vol} | {mat}m | {expected:.{dp}f} | {actual:.{dp}f} | {sign}{delta:.0f}")

    return "\n".join(lines)


def _commit_list_rates():
    """Commit updated list_rates.csv directly to the current branch.

    Deliberately does NOT raise on ANY step's failure (add, commit or push):
    this runs before the more important discount-structure detection
    (steps 3a-5a), and the on-disk list_rates.csv is already updated regardless
    (analyze_list_rates_minimal wrote it) -- a transient git hiccup here should
    not abort same-day detection of a real pricing-structure change. Tomorrow's
    run retries it."""

    repo_root = CODE_DIR.parent
    steps = [
        ['git', 'add', 'data/list_rates.csv'],
        ['git', '-c', f'user.name={GIT_IDENTITY_NAME}', '-c', f'user.email={GIT_IDENTITY_EMAIL}',
         'commit', '-m', 'Update list_rates.csv (auto-detected rate change)'],
        ['git', 'push'],
    ]
    for cmd in steps:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_root)
        if result.returncode != 0:
            print(f"  Warning: {' '.join(cmd)} failed: {combined_output(result)}")
            return

    print("  Committed and pushed list_rates.csv")


def _write_pipeline_state_json(state):
    """
    Write pipeline state to pipeline_state.json. Shared by the normal write below
    and the amend-after-email-failure write in _run_pipeline_or_email_failure, so
    the two can't silently drift apart (e.g. if the trigger_reason filter below
    ever grows another condition).
    """
    state_file = data_dir() / 'pipeline_state.json'
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # trigger_reason is set unconditionally whenever a deep run starts (even a
    # successful one), so it stays in `state` for in-memory use -- but it's only
    # meaningful once a run has actually failed. Leave it out of the persisted
    # JSON (also dumped verbatim into the GitHub Actions step summary) on any
    # other run, so a normal deep-run success doesn't carry a stray key that
    # looks like a failure signal.
    to_dump = {k: v for k, v in state.items() if k != 'trigger_reason' or state['email_type'] == 'pipeline_failed'}
    with open(state_file, 'w') as f:
        json.dump(to_dump, f, indent=2)
    return state_file


def _finalize_and_send_email(state, is_test):
    """Write pipeline state to JSON, send email, return state."""
    state_file = _write_pipeline_state_json(state)
    print(f"\n[State] Written to {state_file}")

    print(f"\n[Step 8] Sending email ({state['email_type']})...")
    diagnostics = state.get('force_shallow_diagnostics')
    email_sent = step_8.send_email_with_report(
        email_type=state['email_type'],
        pr_url=state['pr_url'],
        list_rate_changes=state['list_rate_changes'],
        is_test=is_test,
        force_shallow_diagnostics=diagnostics,
        rate_dp=state.get('rate_precision', 2),
        maturity_changes=state.get('maturity_changes'),
        failure_reason=state.get('failure_reason'),
        trigger_reason=state.get('trigger_reason'),
        failure_location=state.get('failure_location'),
        break_lines_changed=state.get('break_lines_changed'),
    )
    print(f"  Email sent: {email_sent}")

    return state


def _migrate_discount_surfaces_columns(maturity_changes):
    """Add used_for_Xm columns for new maturities to discount_surfaces.csv."""
    csv_path = data_dir() / 'discount_surfaces.csv'
    df = pd.read_csv(csv_path)

    for m in maturity_changes['added']:
        col = f'used_for_{m}m'
        if col not in df.columns:
            df[col] = 0
            df[col] = df[col].astype('int64')
            print(f"  Added column '{col}' with default value 0")

    df.to_csv(csv_path, index=False)


def _deep_scrape_rebuild_surfaces_validate_and_open_pr(state, deep_run_signal):
    """Run the deep scrape pipeline (steps 5b through 7). Updates state in place.

    Sets state['trigger_reason'] itself (rather than leaving it to callers) so
    the failure alert can tell a deep-run crash apart from a light-run crash
    regardless of how many call sites this function ever gets."""
    state['trigger_reason'] = deep_run_signal['reason']

    # Step 5b: Open feature branch
    print("\n[Step 5b] Opening feature branch...")
    branch_name = step_5b.open_feature_branch(deep_run_signal)
    print(f"  Branch: {branch_name}")

    # Write updated VALID_MATURITIES to disk if maturity change triggered this
    if state.get('maturity_changes'):
        print("\n[Maturity Update] Writing updated VALID_MATURITIES to io_contracts.py...")
        update_valid_maturities_on_disk(VALID_MATURITIES)

    # Step 6a: Scrape refined grid
    print("\n[Step 6a] Scraping refined grid...")
    refined_scraper_df = step_6a.scrape_refined_grid()
    print(f"  Got {len(refined_scraper_df)} rows")

    # Step 6b: Check list rates from deep scrape
    print("\n[Step 6b] Checking list rates from deep scrape...")
    list_rate_check = step_6b.analyze_list_rates_refined(refined_scraper_df)
    print(f"  List rate changes in refined: {list_rate_check is not None}")

    # Step 6c: Extract rasterized discount surfaces
    print("\n[Step 6c] Extracting rasterized discount surfaces...")
    rasterized_surfaces, ltv_probes, vol_probes = step_6c.extract_rasterized_surfaces(refined_scraper_df)
    print(f"  Surfaces for {len(rasterized_surfaces)} maturities")
    print(f"  LTV probes: {len(ltv_probes)}, VOL probes: {len(vol_probes)}")

    # Step 6d: Extract minimal break lines
    print("\n[Step 6d] Extracting minimal break lines...")
    break_lines = step_6d.extract_minimal_break_lines(rasterized_surfaces, ltv_probes, vol_probes)
    print(f"  LTV breaks: {break_lines['ltv_breaks']}")
    print(f"  VOL breaks: {break_lines['vol_breaks']}")

    # Step 6e: Make bins from break lines
    print("\n[Step 6e] Making bins from break lines...")
    bins = step_6e.make_bins_from_break_lines(break_lines)
    print(f"  LTV bins: {len(bins['LTV_BINS'])} edges, {len(bins['LTV_LABELS'])} labels")
    print(f"  VOL bins: {len(bins['VOL_BINS'])} edges, {len(bins['VOL_LABELS'])} labels")

    # Step 6f: Close deprecated discount surfaces
    print("\n[Step 6f] Closing deprecated discount surfaces...")
    rows_closed = step_6f.close_deprecated_disc_surfaces()
    print(f"  Closed {rows_closed} rows")

    # Step 6g: Create new discount surface rows
    print("\n[Step 6g] Creating new discount surface rows...")
    rows_created = step_6g.create_new_disc_surface(bins, rasterized_surfaces, ltv_probes, vol_probes)
    print(f"  Created {rows_created} rows")

    # Step 6h: Create all PNG visualizations
    print("\n[Step 6h] Creating all PNG visualizations...")
    step_6h.create_all_png_visualizations()

    # Step 6i: Update boundaries_minimal.yaml
    print("\n[Step 6i] Updating boundaries_minimal.yaml...")
    state['break_lines_changed'] = step_6i.update_boundaries_minimal(bins)
    print(f"  Break lines changed: {state['break_lines_changed']}")

    # Step 6j: Validate deep run
    print("\n[Step 6j] Validating deep run...")
    validation_scraper_df = step_1.scrape_minimal_grid()
    validation_result = step_6j.validate_deep_run(validation_scraper_df)
    print(f"  Passed: {validation_result['passed']}")
    if not validation_result['passed']:
        print(f"  Reason: {validation_result['reason']}")

    # Step 7: Open PR (if validation passed)
    if validation_result['passed']:
        print("\n[Step 7] Opening PR...")
        state['pr_url'] = step_7.open_PR_with_updates_to_main(validation_result, branch_name, is_test=state['is_test'])
        assert state['pr_url'], "Step 7 returned no PR URL (commit, push or gh pr create failed - see log above)"
        if not state.get('maturity_changes'):
            state['email_type'] = 'deep_run_started'
        print(f"  PR URL: {state['pr_url']}")
    else:
        print("\n[Step 7] SKIPPED - Validation failed")
        state['email_type'] = 'catastrophic_failure'
        state['pr_url'] = None


def _run_pipeline_steps(state, force_shallow):
    """
    Run the light run, and the deep run if triggered. Mutates state in place.

    Wrapped by _run_pipeline_or_email_failure, which emails and re-raises on
    ANY exception here -- light run or deep run, including the maturity-change
    bookkeeping below. Nothing in this function needs its own try/except: any
    exception raised by a step (an assertion, a failed subprocess) propagates
    straight up and is handled by the wrapper. The one deliberate exception is
    _commit_list_rates, which prints a warning and continues on a git failure
    rather than aborting the more important detection steps that follow it.
    """
    # =========================================================================
    # LIGHT RUN (always)
    # =========================================================================

    # Step 1: Scrape minimal grid
    print("\n[Step 1] Scraping minimal grid...")
    scraper_df = step_1.scrape_minimal_grid()
    print(f"  Got {len(scraper_df)} rows")

    # Check rate precision (SBAB currently uses integer BPs = 2dp)
    dp = rate_precision(scraper_df['offered_interest_rate'])
    state['rate_precision'] = dp
    if dp > 2:
        print(f"  NOTE: Sub-basis-point precision detected ({dp} decimal places)")

    # Step 2: Analyze list rates
    # Runs before 3a/3b because list_rates.csv must be up-to-date before
    # 3a computes discounts (discount = list_rate - offered_rate).
    # With stale list rates, subsequent steps would falsely trigger deep runs.
    # Also must run before maturity check — that path returns early.
    print("\n[Step 2] Analyzing list rates...")
    list_rate_changes = step_2.analyze_list_rates_minimal(scraper_df)
    state['list_rate_changes'] = list_rate_changes
    print(f"  Changes detected: {list_rate_changes is not None}")

    # Persist list rate changes to repo (so tomorrow's run starts fresh)
    if list_rate_changes and os.getenv('GITHUB_TOKEN'):
        print("  Committing list_rates.csv to main...")
        _commit_list_rates()

    # Check for maturity changes (added/removed maturities)
    maturity_changes = detect_maturity_changes(scraper_df)
    if maturity_changes:
        print("\n" + "="*60)
        print("MATURITY CHANGE DETECTED — Phase 2: full continuation")
        print("="*60)
        print(f"  Added:   {sorted(maturity_changes['added']) or 'none'}")
        print(f"  Removed: {sorted(maturity_changes['removed']) or 'none'}")

        state['email_type'] = 'maturity_change'
        state['maturity_changes'] = {
            'added': [int(m) for m in sorted(maturity_changes['added'])],
            'removed': [int(m) for m in sorted(maturity_changes['removed'])],
        }

        # Update VALID_MATURITIES at runtime
        scraped_maturities = sorted(scraper_df['period'].unique())
        print(f"\n[Maturity Update] VALID_MATURITIES: {list(VALID_MATURITIES)} -> {scraped_maturities}")
        update_maturities(scraped_maturities)

        # List rate bookkeeping (close removed, add new)
        print("\n[Maturity Update] Handling list rate changes...")
        list_rate_actions = handle_maturity_change_list_rates(maturity_changes, scraper_df)
        print(f"  Actions: {list_rate_actions}")

        # Migrate discount_surfaces.csv columns for new maturities
        print("\n[Maturity Update] Migrating discount_surfaces.csv columns...")
        _migrate_discount_surfaces_columns(maturity_changes)

        # Force deep run (maturity change always requires full re-discovery)
        deep_run_signal = {
            'trigger_deep_run': True,
            'reason': f"Maturity change: added={sorted(maturity_changes['added'])}, removed={sorted(maturity_changes['removed'])}",
        }

        print("\n" + "="*60)
        print("DEEP RUN TRIGGERED (maturity change)")
        print("="*60)
        # → 5b: open feature branch
        # → 6a-6i: deep scrape refined grid, discover boundaries, rebuild CSVs + PNGs
        # → 6j: validate by re-running light scrape with new boundaries
        # → 7: open PR if validation passed (sets state['pr_url'])
        _deep_scrape_rebuild_surfaces_validate_and_open_pr(state, deep_run_signal)
        return

    # Step 3a: Convert to analysis DataFrames
    print("\n[Step 3a] Converting to analysis DataFrames...")
    todays_pricing, bin_uniform, bin_mean = step_3a.convert_scraper_to_analysis_dfs(scraper_df)
    print(f"  todays_pricing: {todays_pricing.shape}")
    print(f"  bin_uniform: {bin_uniform.shape}")
    print(f"  bin_mean: {bin_mean.shape}")

    # Step 3b: Create PNGs
    print("\n[Step 3b] Creating all PNG visualizations (shallow)...")
    step_3b.create_all_png_visualizations_shallow()

    # Step 4: Analyze shape (uniformity check)
    print("\n[Step 4] Analyzing shape...")
    deep_run_signal = step_4.analyze_shape(bin_uniform, bin_mean)
    print(f"  Trigger deep run: {deep_run_signal['trigger_deep_run']}")
    if deep_run_signal['trigger_deep_run']:
        print(f"  Reason: {deep_run_signal['reason']}")

    # Step 5a: Categorize email type
    print("\n[Step 5a] Categorizing email type...")
    state['email_type'] = step_5a.categorize_email_type(
        list_rate_changes,
        deep_run_signal
    )
    print(f"  Email type: {state['email_type']}")

    # =========================================================================
    # DEEP RUN (if triggered)
    # =========================================================================

    if deep_run_signal['trigger_deep_run'] and force_shallow:
        print("\n" + "="*60)
        print("DEEP RUN WOULD TRIGGER — but --force-shallow is set")
        print("="*60)
        print(f"  Reason: {deep_run_signal['reason']}")
        details = deep_run_signal.get('details', [])
        for d in details:
            print(f"  {d}")

        deep_run_signal['rate_precision'] = dp
        state['email_type'] = 'no_change'
        state['force_shallow_diagnostics'] = _format_shallow_diagnostics(deep_run_signal)

    elif deep_run_signal['trigger_deep_run']:
        print("\n" + "="*60)
        print("DEEP RUN TRIGGERED")
        print("="*60)
        # → 5b: open feature branch
        # → 6a-6i: deep scrape refined grid, discover boundaries, rebuild CSVs + PNGs
        # → 6j: validate by re-running light scrape with new boundaries
        # → 7: open PR if validation passed (sets state['pr_url'])
        _deep_scrape_rebuild_surfaces_validate_and_open_pr(state, deep_run_signal)


def _crash_site(error):
    """Last traceback frame in our own step code (skipping io_contracts asserts and libraries); else the innermost frame."""
    frames = traceback.extract_tb(error.__traceback__)
    ours = [f for f in frames
            if Path(f.filename).parent.resolve() == CODE_DIR.resolve() and Path(f.filename).name != 'io_contracts.py']
    return (ours or frames)[-1]


def _run_pipeline_or_email_failure(state, is_test, force_shallow):
    """Run the pipeline. If ANYTHING crashes -- light run or deep run -- email the
    failure before re-raising (a red job alone notifies nobody). state['trigger_reason']
    is only set if a deep run had started, so the alert can tell the two cases apart."""
    try:
        _run_pipeline_steps(state, force_shallow)
    except Exception as e:
        crash_site = _crash_site(e)
        state['email_type'] = 'pipeline_failed'
        state['failure_reason'] = f"{type(e).__name__}: {e}"
        state['failure_location'] = f"{Path(crash_site.filename).name}:{crash_site.lineno} in {crash_site.name}"
        try:
            _finalize_and_send_email(state, is_test)
        except Exception as email_error:
            # Could be a failure to write pipeline_state.json (the first thing
            # _finalize_and_send_email does) OR a failure to send the email itself --
            # from here we can't tell which, so the message doesn't commit to either.
            print(f"  ERROR: could not finalize the failure alert (state write or email send): {type(email_error).__name__}: {email_error}")
            # If the write succeeded and only the send failed, pipeline_state.json
            # already exists from that normal write -- amend it so the workflow's step
            # summary (which reads this same file) doesn't confidently tell the reader
            # to "see the failure email" when no such email actually went out. Guarded:
            # if even this write fails (e.g. disk full), that must not replace the real
            # crash as what propagates -- print and move on, same as the failure above.
            state['email_send_failed'] = f"{type(email_error).__name__}: {email_error}"
            try:
                _write_pipeline_state_json(state)
            except Exception as write_error:
                print(f"  ERROR: could not record email_send_failed either: {type(write_error).__name__}: {write_error}")
        raise


def run_pipeline(is_test=False, force_shallow=False, data_dir_override=None):
    """
    Run the full SBAB monitoring pipeline.

    Args:
        is_test: If True, prepend "TEST EMAIL:" to notifications
        force_shallow: If True, never escalate to deep run. Instead send
                       diagnostic email showing what would have triggered it.
        data_dir_override: If set, override data directory for testing.
                            Forces is_test=True regardless of the is_test
                            argument -- see comment at the override site.

    Returns:
        dict: Final pipeline state

    A crash in the light run or deep run is emailed as a 'pipeline_failed' alert
    before the exception is re-raised (see _run_pipeline_or_email_failure). The
    job still exits non-zero either way. NOT covered: a crash in the
    --data-dir-override preamble just below (malformed valid_maturities.json)
    or in sending the final success email (see the try/except around it) --
    neither is on the production cron's path, and the latter can't usefully
    alert about the very email mechanism that's failing.
    """
    # Override data directory if testing with fixture CSVs
    if data_dir_override:
        # A non-default data_dir has no legitimate production use -- it only ever
        # points at fixture data. Force test-mode behavior here, as the single
        # source of truth, rather than relying on is_test also being set
        # correctly by the caller (GitHub Actions' manual-dispatch form has them
        # as two independent inputs). Without this, forgetting to also flip
        # is_test would let fixture numbers get committed over production data
        # and a normal-looking (non-"DO NOT MERGE") PR and email go out.
        if not is_test:
            print("[Test] data_dir override set without is_test=True -- forcing test mode")
            is_test = True

        os.environ['SBAB_DATA_DIR'] = str(Path(data_dir_override).resolve())
        print(f"[Test] Data directory: {os.environ['SBAB_DATA_DIR']}")

        # Load maturity override if present
        maturities_file = data_dir() / 'valid_maturities.json'
        if maturities_file.exists():
            with open(maturities_file) as f:
                override = json.load(f)
            update_maturities(override)
            print(f"[Test] Overrode VALID_MATURITIES: {override}")

    today_str = date.today().strftime('%Y-%m-%d')
    print(f"{'='*60}")
    print(f"SBAB Pipeline - {today_str}")
    print(f"Mode: {'TEST' if is_test else 'PRODUCTION'}")
    print(f"{'='*60}")

    # Initialize state
    state = {
        'date': today_str,
        'is_test': is_test,
        'email_type': 'no_change',
        'pr_url': None,
        'list_rate_changes': None,
        'break_lines_changed': None,
    }

    _run_pipeline_or_email_failure(state, is_test, force_shallow)

    # =========================================================================
    # ALWAYS: Send email (only reached if _run_pipeline_or_email_failure did
    # not re-raise; it sends its own alert and re-raises on any crash)
    # =========================================================================

    try:
        state = _finalize_and_send_email(state, is_test)
        print("\n" + "="*60)
        print("PIPELINE COMPLETE")
        print("="*60)
        return state
    except Exception as e:
        # The pipeline itself succeeded; only sending the report failed (e.g. an
        # SMTP outage). Say so plainly in the log -- a bare traceback here could
        # otherwise be misread as the pipeline itself having crashed.
        print(f"\n{'='*60}\nPIPELINE SUCCEEDED BUT THE REPORT EMAIL FAILED TO SEND\n{'='*60}")
        print(f"  {type(e).__name__}: {e}")
        raise


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='SBAB Rate Monitor Pipeline')
    parser.add_argument('--force-shallow', action='store_true',
                        help='Never escalate to deep run. Send diagnostic email instead.')
    parser.add_argument('--data-dir',
                        help='Override data directory (for testing with fixture CSVs)')

    args = parser.parse_args()

    # Read IS_TEST from environment
    is_test = os.getenv('IS_TEST', 'false').lower() == 'true'

    run_pipeline(is_test=is_test, force_shallow=args.force_shallow, data_dir_override=args.data_dir)
