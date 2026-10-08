"""
Step 6b: Analyze List Rates (Refined Grid) - DEEP RUN

Re-checks list rates using the refined grid scrape from step 6a.
The refined grid probes more (LTV, VOL) points, so may find higher max rates
that the minimal grid missed.

INPUTS:
    - pd.DataFrame from step 6a (refined scraper output)
    - data/list_rates.csv

OUTPUTS:
    - None if no changes
    - dict of {maturity: {'old', 'new', 'delta'}} if changes
    - SIDE EFFECT: Updates list_rates.csv if changes detected

NOTE: If step 2 already updated list_rates.csv today, this step will
OVERWRITE those values if it finds higher max rates. This is intentional.

I/O CONTRACT: see monitor_list_rate.py

IMPLEMENTATION:
    Thin wrapper around monitor_list_rate.analyze_list_rates()
"""
from monitor_list_rate import analyze_list_rates


def analyze_list_rates_refined(scraper_df, list_rates_path=None):
    """Check if list rates have changed (refined grid)."""
    return analyze_list_rates(scraper_df, list_rates_path)
