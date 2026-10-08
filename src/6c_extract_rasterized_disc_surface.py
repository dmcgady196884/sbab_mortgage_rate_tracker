"""
Step 6c: Extract Rasterized Discount Surfaces (DEEP RUN)

Takes the dense scrape from step 6a and extracts the discount surface for each
maturity. "Rasterized" = we have a value at every probed (LTV, VOL) point,
forming a 2D grid of discounts.

INPUTS:
    1. pd.DataFrame from step 6a (dense scraper output, same schema as step 1)
    2. data/list_rates.csv (to compute discount = list_rate - offered_rate)

OUTPUTS:
    - Tuple: (rasterized_surfaces, ltv_probes, vol_probes)
        - rasterized_surfaces: {maturity: 2D np.ndarray of discounts}
        - ltv_probes: sorted list of LTV values (floats)
        - vol_probes: sorted list of VOL values (ints)
    - Array shape: (n_ltv_probes, n_vol_probes)
    - Values: float64, 2 decimal places (integer basis points)

I/O CONTRACT (from io_contracts.py):
    Input:  assert_scraper_output(dense_scrape_df)
    Output: assert_rasterized_surfaces(rasterized_surfaces)  # validates the dict only
    Note: ltv_probes and vol_probes are auxiliary return values, not asserted

COMPUTATION:
    For each (LTV_probe, VOL_probe, maturity) triple:
        discount = list_rate[maturity] - offered_rate

    The list_rate is looked up from list_rates.csv (the current valid row,
    where valid_to is empty).

CONTEXT:
    - This is step 3 of the DEEP RUN ONLY section (after 6a scraper, 6b list check)
    - Fed into 6d (extract break lines) and 6f (create new discount surface)
    - The "rasterized" representation is dense; 6f will compress it to bins
"""
from pathlib import Path

import numpy as np
import pandas as pd

from io_contracts import assert_scraper_output, assert_rasterized_surfaces, VALID_MATURITIES, rate_precision, data_dir


def load_current_list_rates(list_rates_path=None):
    """
    Load current list rates from CSV (rows where valid_to is empty).

    Returns:
        dict: {maturity: list_rate}
    """
    if list_rates_path is None:
        list_rates_path = data_dir() / 'list_rates.csv'

    df = pd.read_csv(list_rates_path)
    # Current rates have empty valid_to
    current = df[df['valid_to'].isna() | (df['valid_to'] == '')]

    return dict(zip(current['maturity'], current['list_rate']))


def extract_rasterized_surfaces(dense_scrape_df, list_rates_path=None):
    """
    Extract rasterized discount surfaces from dense scraper output.

    Args:
        dense_scrape_df: DataFrame from step 6a with columns
            [ltv, loan_amount, period, offered_interest_rate, ...]
        list_rates_path: Optional path to list_rates.csv

    Returns:
        tuple: (rasterized_surfaces, ltv_probes, vol_probes)
            - rasterized_surfaces: {maturity: 2D np.ndarray} for each of 8 maturities
            - ltv_probes: sorted list of LTV values (floats)
            - vol_probes: sorted list of VOL values (ints)
    """
    assert_scraper_output(dense_scrape_df)

    list_rates = load_current_list_rates(list_rates_path)
    dp = rate_precision(dense_scrape_df['offered_interest_rate'])

    # Get sorted unique probe points
    ltv_probes = sorted(dense_scrape_df['ltv'].unique())
    vol_probes = sorted(dense_scrape_df['loan_amount'].unique())

    # Create index mappings
    ltv_to_idx = {v: i for i, v in enumerate(ltv_probes)}
    vol_to_idx = {v: i for i, v in enumerate(vol_probes)}

    n_ltv = len(ltv_probes)
    n_vol = len(vol_probes)

    # Initialize output arrays
    rasterized_surfaces = {}
    for maturity in VALID_MATURITIES:
        rasterized_surfaces[maturity] = np.full((n_ltv, n_vol), np.nan, dtype=np.float64)

    # Fill arrays
    for _, row in dense_scrape_df.iterrows():
        ltv_idx = ltv_to_idx[row['ltv']]
        vol_idx = vol_to_idx[row['loan_amount']]
        maturity = row['period']
        offered_rate = row['offered_interest_rate']

        list_rate = list_rates.get(maturity)
        if list_rate is not None:
            discount = round(list_rate - offered_rate, dp)
            rasterized_surfaces[maturity][ltv_idx, vol_idx] = discount

    # Validate no NaNs remain - every probe point should be filled
    for maturity in VALID_MATURITIES:
        nan_count = np.isnan(rasterized_surfaces[maturity]).sum()
        assert nan_count == 0, \
            f"Rasterized surface for {maturity}m has {nan_count} NaN values. " \
            f"This indicates missing probe data in the scraper output."

    assert_rasterized_surfaces(rasterized_surfaces)
    return rasterized_surfaces, ltv_probes, vol_probes
