"""
Step 1: Scrape SBAB API on Minimal Grid

Scrapes SBAB's public API using the minimal set of (LTV, VOL) probe points
defined in boundaries_minimal.yaml. Probes on BOTH sides of each boundary
(+/- epsilon) to detect which side of a price discontinuity each point falls on.

RAW API FORMAT:
    URL: https://www.sbab.se/www-open-rest-api/resources/rantor/bolan/hamtaprisdiffaderantor/{asset_val}/{loan_vol}

    Response (JSON array, one entry per maturity):
    [
        {"LoptidText":"2026-04-23", "Rantesats":2.65, "Rantebindningstid":3,  "EffektivRantesats":0.0},
        {"LoptidText":"2027-01-25", "Rantesats":2.77, "Rantebindningstid":12, "EffektivRantesats":0.0},
        ...  # 8 entries total: maturities 3, 12, 24, 36, 48, 60, 84, 120
    ]

    Field mapping:
        - LoptidText: maturity date (string, ignored)
        - Rantesats: offered interest rate (float, 2dp) -> offered_interest_rate
        - Rantebindningstid: maturity period in months (int) -> period
        - EffektivRantesats: effective rate (always 0.0, ignored)

INPUTS:
    - boundaries_minimal.yaml (defines LTV and VOL probe points)
    - SBAB's public API (live or test fixture)

OUTPUTS:
    - pd.DataFrame with columns: [url, loan_amount, ltv, period,
      offered_interest_rate, scraped_at, bank, json]
    - One row per (LTV, VOL, maturity) combination (8 rows per API call)
    - ~800 API calls for minimal grid = ~6400 rows

I/O CONTRACT (from io_contracts.py):
    Output: assert_scraper_output(df)
    Schema: SCRAPER_OUTPUT_SCHEMA
        columns: [url, loan_amount, ltv, period, offered_interest_rate, scraped_at, bank, json]
        dtypes: {loan_amount: int64, ltv: float64, period: int64,
                 offered_interest_rate: float64 (2dp), ...}

IMPLEMENTATION:
    This is a thin wrapper. The actual scraper logic lives in:
        extract_API_results_on_config_grid.py

    Both step 1 and step 6a call the SAME scraper function, just with different
    boundary config files (boundaries_minimal.yaml vs boundaries_refined.yaml).

NOTES:
1. While the API takes (asset_val, loan_vol)-pairs, SBAB prices in (LTV, VOL)-space, i.e.
   (loan_vol/asset_val, loan_vol) = (LTV, VOL). Historical price discontinuities:
   - VOL: (500k, 600k, 700k, 800k, 900k, 1M, 1.5M, 2M, 2.5M, 3M, 3.5M, 4.5M, 5M) SEK
   - LTV: (50%, 60%, 65%, 70%, 75%, 76%, 77%, 78%, 79%, 80%, 85%)
   The boundaries_minimal.yaml specifies which of these are relevant.

2. The scraper CANNOT query exactly ON boundaries - it probes +/- epsilon from each.

3. PROMINENT BOUNDARIES (see io_contracts.py; none by default), if set, are always present in
   boundaries_minimal.yaml, even if SBAB has no price discontinuity there. They are user-input
   proxies for LTV/VOL break-lines that are important to the user's goals.
"""
from extract_API_results_on_config_grid import scrape_on_grid


def scrape_minimal_grid():
    """Scrape SBAB API using minimal probe grid."""
    return scrape_on_grid('boundaries_minimal.yaml')
