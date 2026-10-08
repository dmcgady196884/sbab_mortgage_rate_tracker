"""
Step 4: Analyze Discount Surface Shape

Checks if SBAB's discount surface structure has changed compared to what's on file.
This is the step that decides whether to trigger a DEEP RUN.

Two failure modes that trigger deep run:

1. NON-UNIFORMITY: A bin that was previously flat (same price across all points
   within the bin) is no longer flat.
   - Detected via: any flat_{N}m = False in discount_surfaces_BIN_uniform_df
   - Meaning: bin boundaries are wrong, need to rediscover break lines
   - Output reason: "Non-uniformities detected: need to trigger deep-run"

2. VALUE MISMATCH: The mean discount in a bin differs from what's on file.
   - Detected via: comparing discount_surfaces_BIN_mean_df to current discount_surfaces.csv
   - Meaning: SBAB changed their discount structure
   - Output reason: "Changes in discounts detected: triggering deep-run"

INPUTS:
    1. discount_surfaces_BIN_uniform_df from step 3a
    2. discount_surfaces_BIN_mean_df from step 3a
    3. data/discount_surfaces.csv (current valid surface, where valid_to is empty)

OUTPUTS:
    - dict: {'trigger_deep_run': bool, 'reason': str or None}
    - If trigger_deep_run = False: reason = None
    - If trigger_deep_run = True: reason explains why (non-uniformity vs value mismatch)

I/O CONTRACT (from io_contracts.py):
    Input:  assert_bin_uniform_df(discount_surfaces_BIN_uniform_df)
            assert_bin_mean_df(discount_surfaces_BIN_mean_df)
    Output: assert_deep_run_signal(result)

CONTEXT:
    - If this step returns trigger_deep_run = True, step 5b creates a feature branch
      and the deep run (steps 6a-6j) executes.
    - If trigger_deep_run = False, we skip straight to step 8 (send email).
"""
from pathlib import Path

import pandas as pd

from io_contracts import (
    assert_bin_uniform_df,
    assert_bin_mean_df,
    assert_deep_run_signal,
    VALID_MATURITIES,
    rate_precision,
    data_dir,
)


def load_current_discount_surface(disc_csv_path=None):
    """Load current discount surface (where valid_to is empty)."""
    if disc_csv_path is None:
        disc_csv_path = data_dir() / 'discount_surfaces.csv'
    df = pd.read_csv(disc_csv_path)
    current = df[df['valid_to'].isna() | (df['valid_to'] == '')]
    return current


def check_uniformity(bin_uniform_df):
    """Check if all bins are uniform. Returns list of non-uniform (ltv_bin, vol_bin, maturity) tuples."""
    non_uniform = []
    flat_cols = [c for c in bin_uniform_df.columns if c.startswith('flat_')]

    for _, row in bin_uniform_df.iterrows():
        for col in flat_cols:
            if not row[col]:
                maturity = int(col.replace('flat_', '').replace('m', ''))
                non_uniform.append((row['ltv_bin'], row['vol_bin'], maturity))

    return non_uniform


def check_value_mismatch(bin_mean_df, current_surface):
    """
    Check if mean discounts match current surface on file.
    Returns list of mismatched (ltv_bin, vol_bin, maturity, expected, actual) tuples.
    """
    # Detect precision from stored surface values
    dp = rate_precision(current_surface['discount'])
    mismatches = []
    compared = 0

    for _, row in bin_mean_df.iterrows():
        ltv_bin = row['ltv_bin']
        vol_bin = row['vol_bin']

        for m in VALID_MATURITIES:
            mean_col = f'mean_discount_{m}m'
            used_col = f'used_for_{m}m'

            actual_discount = row[mean_col]
            if pd.isna(actual_discount):
                continue

            # Find expected discount from current surface
            mask = (
                (current_surface['ltv_bin'] == ltv_bin) &
                (current_surface['vol_bin'] == vol_bin) &
                (current_surface[used_col] == 1)
            )
            matching = current_surface[mask]

            # Bins are built from the stored boundaries, so every bin normally has a
            # stored row. An individual bin with no stored row is skipped, not treated as
            # a change (see the assert below for the case where nothing matches at all).
            if len(matching) == 0:
                continue

            expected_discount = matching.iloc[0]['discount']
            compared += 1

            if round(actual_discount, dp) != round(expected_discount, dp):
                mismatches.append((ltv_bin, vol_bin, m, expected_discount, actual_discount))

    # If NOTHING matched, the scrape and the stored surface use different bins; reporting
    # "no change" would be wrong, so fail loudly instead.
    assert compared > 0, \
        "step 4: no scraped bin matches the stored discount surface (different bin labels?)"

    return mismatches


def analyze_shape(bin_uniform_df, bin_mean_df, disc_csv_path=None):
    """
    Check if discount surface shape has changed.

    Args:
        bin_uniform_df: from step 3a (per-bin uniformity flags)
        bin_mean_df: from step 3a (per-bin mean discounts)
        disc_csv_path: path to discount_surfaces.csv

    Returns:
        dict: {'trigger_deep_run': bool, 'reason': str or None}
    """
    assert_bin_uniform_df(bin_uniform_df)
    assert_bin_mean_df(bin_mean_df)

    current_surface = load_current_discount_surface(disc_csv_path)

    # Check 1: Non-uniformity
    non_uniform = check_uniformity(bin_uniform_df)
    if non_uniform:
        result = {
            'trigger_deep_run': True,
            'reason': f'Non-uniformity detected in {len(non_uniform)} bin/maturity combinations',
            'details': non_uniform,
        }
        assert_deep_run_signal(result)
        return result

    # Check 2: Value mismatch
    mismatches = check_value_mismatch(bin_mean_df, current_surface)
    if mismatches:
        result = {
            'trigger_deep_run': True,
            'reason': f'Discount value mismatch in {len(mismatches)} bin/maturity combinations',
            'details': mismatches,
        }
        assert_deep_run_signal(result)
        return result

    # All good
    result = {'trigger_deep_run': False, 'reason': None, 'details': []}
    assert_deep_run_signal(result)
    return result
