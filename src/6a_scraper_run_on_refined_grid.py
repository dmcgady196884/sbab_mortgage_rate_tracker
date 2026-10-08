"""
Step 6a: Scrape SBAB API on Refined Grid (DEEP RUN)

Scrapes SBAB's API using a MUCH denser grid of (LTV, VOL) points than the
minimal grid used in step 1. This is expensive (~thousands of API calls) and
only runs when we need to rediscover the full discount surface structure.

INPUTS:
    - boundaries_refined.yaml (dense probe points)
    - SBAB's public API

OUTPUTS:
    - pd.DataFrame with same schema as step 1, but many more rows
    - ~4000 API calls = ~32000 rows (8 maturities per call)

I/O CONTRACT (from io_contracts.py):
    Output: assert_scraper_output(df)
    Schema: SCRAPER_OUTPUT_SCHEMA (same as step 1)

IMPLEMENTATION:
    This is a thin wrapper. The actual scraper logic lives in:
        extract_API_results_on_config_grid.py

    Both step 1 and step 6a call the SAME scraper function, just with different
    boundary config files (boundaries_minimal.yaml vs boundaries_refined.yaml).

PERFORMANCE NOTE:
    SBAB doesn't seem to rate-limit aggressively. Requests are sent one at a time,
    with no deliberate throttle beyond request latency; a failed request is retried
    after a short delay (see extract_API_results_on_config_grid.py).
"""
from extract_API_results_on_config_grid import scrape_on_grid


def scrape_refined_grid():
    """Scrape SBAB API using dense refined probe grid."""
    return scrape_on_grid('boundaries_refined.yaml')
