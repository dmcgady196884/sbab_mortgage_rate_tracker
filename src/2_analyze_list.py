"""
Step 2: Analyze List Rates (Minimal Grid)

Checks if SBAB's list rates have changed compared to what's on file.
Uses the minimal grid scrape from step 1.

INPUTS:
    - pd.DataFrame from step 1 (scraper output)
    - data/list_rates.csv

OUTPUTS:
    - None if no changes
    - dict of {maturity: {'old', 'new', 'delta'}} if changes
    - SIDE EFFECT: Updates list_rates.csv if changes detected

I/O CONTRACT: see monitor_list_rate.py

IMPLEMENTATION:
    Thin wrapper around monitor_list_rate.analyze_list_rates()
"""
from monitor_list_rate import analyze_list_rates


def analyze_list_rates_minimal(scraper_df, list_rates_path=None):
    """Check if list rates have changed (minimal grid)."""
    return analyze_list_rates(scraper_df, list_rates_path)
