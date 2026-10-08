"""
Step 6j: Validate Deep Run (DEEP RUN)

Validation step: Re-runs the light scraper logic (steps 3a → 4) using the
freshly scraped minimal grid data. If step 4 STILL triggers a deep run,
something is catastrophically wrong - our newly discovered surface doesn't
match what we just scraped.

This is the FINAL GATE before opening a PR. If validation fails, the PR is
NOT opened and the email flag is set to "catastrophic_failure".

VALIDATION CHECKS:
    1. Run step 3a on fresh minimal grid scrape
    2. Run step 4 to check for non-uniformity or value mismatch
    3. If step 4 would trigger another deep run → FAIL

INPUTS:
    - Fresh scraper output from minimal grid (pd.DataFrame)
      (The orchestrator handles the actual re-scrape using updated boundaries)

OUTPUTS:
    - dict: {'passed': bool, 'reason': str or None}
    - If passed = False, reason explains what went wrong

I/O CONTRACT (from io_contracts.py):
    Input:  assert_scraper_output(scraper_df)
    Output: assert_validation_result(result)

FAILURE MODES:
    1. "Non-uniformity persists": Bins still have non-uniform discounts
    2. "Value mismatch persists": Discount values don't match CSV
    3. "API changed during deep run": SBAB changed prices while we were running

CONTEXT:
    - This is step 10 of the DEEP RUN ONLY section (final validation)
    - If passed: step 7 opens PR
    - If failed: step 7 is skipped, email flag set to "catastrophic_failure"
"""
from io_contracts import assert_scraper_output, assert_validation_result

# Import step modules
from importlib import import_module


def validate_deep_run(scraper_df):
    """
    Validate that the deep run produced a consistent discount surface.

    Args:
        scraper_df: Fresh scraper output from minimal grid

    Returns:
        dict: {'passed': bool, 'reason': str or None}
    """
    assert_scraper_output(scraper_df)

    # Run step 3a: convert scraper output to analysis DataFrames
    step_3a = import_module('3a_convert_csv_to_nice_pd_df')
    todays_pricing, bin_uniform, bin_mean = step_3a.convert_scraper_to_analysis_dfs(scraper_df)

    # Run step 4: check if deep run would be triggered
    step_4 = import_module('4_analyze_shape')
    deep_run_signal = step_4.analyze_shape(bin_uniform, bin_mean)

    if deep_run_signal['trigger_deep_run']:
        result = {
            'passed': False,
            'reason': f"Validation failed: {deep_run_signal['reason']}"
        }
    else:
        result = {
            'passed': True,
            'reason': None
        }

    assert_validation_result(result)
    return result
