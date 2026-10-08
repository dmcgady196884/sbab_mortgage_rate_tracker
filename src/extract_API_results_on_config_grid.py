"""
Shared Scraper Module: Extract API Results on Config Grid

This module contains the core scraper logic shared by step 1 (minimal grid)
and step 6a (refined grid). Both steps call scrape_on_grid() with different
boundary config files.

USAGE:
    from extract_API_results_on_config_grid import scrape_on_grid

    # Step 1 (light run, ~800 API calls):
    df = scrape_on_grid('boundaries_minimal.yaml')

    # Step 6a (deep run, ~4000 API calls):
    df = scrape_on_grid('boundaries_refined.yaml')

API FORMAT:
    URL: https://www.sbab.se/www-open-rest-api/resources/rantor/bolan/hamtaprisdiffaderantor/{asset_val}/{loan_vol}

    Response (JSON array, one entry per maturity):
    [
        {"LoptidText": "2026-04-23", "Rantesats": 2.65, "Rantebindningstid": 3, "EffektivRantesats": 0.0},
        {"LoptidText": "2027-01-25", "Rantesats": 2.77, "Rantebindningstid": 12, "EffektivRantesats": 0.0},
        ...  # 8 entries total: maturities 3, 12, 24, 36, 48, 60, 84, 120
    ]

    Field mapping:
        - LoptidText: maturity date (string, ignored)
        - Rantesats: offered interest rate (float, 2dp) -> offered_interest_rate
        - Rantebindningstid: maturity period in months (int) -> period
        - EffektivRantesats: effective rate (always 0.0, ignored)

OUTPUT SCHEMA (same for both step 1 and 6a):
    columns: [url, loan_amount, ltv, period, offered_interest_rate, scraped_at, bank, json]
    dtypes: {loan_amount: int64, ltv: float64, period: int64,
             offered_interest_rate: float64 (2dp), ...}
    One row per (LTV, VOL, maturity) combination (8 rows per API call)

PROBE POINT GENERATION:
    The boundary config YAML defines bin edges. Probe points are generated
    on BOTH sides of each boundary (+/- epsilon):
        - LTV: ±0.001 (0.1%) from each boundary
        - VOL: ±50 SEK from each boundary

    This ensures we detect which side of a price discontinuity each point falls on.

I/O CONTRACT (from io_contracts.py):
    Input:  assert_api_response(data)  — raw JSON from each API call
    Output: assert_scraper_output(df)
    Schema: SCRAPER_OUTPUT_SCHEMA
"""
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from io_contracts import (
    assert_api_response, assert_scraper_output,
    LTV_EPSILON, VOL_EPSILON, SENTINEL_VOL,
    LTV_PROBE_LOW, LTV_PROBE_HIGH, VOL_PROBE_LOW, VOL_PROBE_HIGH,
    SCRAPER_MAX_RETRIES, SCRAPER_RETRY_DELAY_SECONDS, SCRAPER_USER_AGENT, SCRAPER_PAUSE_SECONDS,
    data_dir,
)

BASE_URL = "https://www.sbab.se/www-open-rest-api/resources/rantor/bolan/hamtaprisdiffaderantor"
TIMEOUT = 30  # seconds


def load_boundaries(config_file):
    """Load LTV and VOL bin edges from YAML config."""
    # boundaries_minimal.yaml lives in data/, boundaries_refined.yaml in src/
    config_path = data_dir() / config_file
    if not config_path.exists():
        config_path = Path(__file__).parent / config_file
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config['ltv_bins'], config['vol_bins']


def generate_probe_points(ltv_bins, vol_bins):
    """
    Generate probe points on both sides of each boundary.

    Returns list of (ltv, vol) tuples to query.
    """
    # NOTE: The YAML configs contain sentinel values (SENTINEL_LTV for LTV, SENTINEL_VOL
    # for VOL) to mark "infinity" bins like "(85+)%" and "(5+)M". We skip these when
    # generating probes — SBAB's pricing is flat beyond the last real boundary.

    # Generate LTV probe points: both sides of each boundary
    ltv_probes = set()
    for ltv in ltv_bins:
        if 0 < ltv < 1:  # Skip 0 and sentinel values
            ltv_probes.add(ltv - LTV_EPSILON)
            ltv_probes.add(ltv + LTV_EPSILON)
    ltv_probes.add(LTV_PROBE_LOW)
    ltv_probes.add(LTV_PROBE_HIGH)

    # Generate VOL probe points: both sides of each boundary
    vol_probes = set()
    for vol in vol_bins:
        if 0 < vol < SENTINEL_VOL:  # Skip 0 and sentinel values
            vol_probes.add(vol - VOL_EPSILON)
            vol_probes.add(vol + VOL_EPSILON)
    vol_probes.add(VOL_PROBE_LOW)
    vol_probes.add(VOL_PROBE_HIGH)

    # Generate all (ltv, vol) combinations
    return [(ltv, vol) for ltv in sorted(ltv_probes) for vol in sorted(vol_probes)]


def scrape_on_grid(boundary_config_file):
    """
    Scrape SBAB API using probe points defined in the given boundary config.

    Args:
        boundary_config_file: str, filename of YAML config (e.g., 'boundaries_minimal.yaml')

    Returns:
        pd.DataFrame with columns: [url, loan_amount, ltv, period,
                                    offered_interest_rate, scraped_at, bank, json]
    """
    ltv_bins, vol_bins = load_boundaries(boundary_config_file)
    probe_points = generate_probe_points(ltv_bins, vol_bins)

    scrape_time = datetime.now().isoformat()
    rows = []  # Collect as list of dicts, convert to DataFrame at end

    total = len(probe_points)
    print(f"Scraping {total} probe points...")

    for i, (ltv, vol) in enumerate(probe_points):
        loan_vol = int(vol)
        # The API takes whole SEK, so asset_val is truncated. For loans above ~1,000 SEK the
        # resulting LTV drift is under 0.0001. For the smallest probe loan (50 SEK) it is
        # larger: 10 of the 780 minimal-grid probes land in the neighbouring LTV bin from the
        # nominal `ltv` recorded below. Harmless today: that loan size has zero discount at
        # every LTV. (Rounding instead of truncating doesn't fix it: 9 of 780 still mismatch.)
        asset_val = int(loan_vol / ltv)
        url = f"{BASE_URL}/{asset_val}/{loan_vol}"

        # A transient error (e.g. an SSL handshake timeout) must not silently drop this
        # probe point: a missing point leaves a hole in the grid that step 6c only
        # catches on a deep run (NaN in the rasterized surface), and never on a light
        # run at all (assert_scraper_output only checks schema, not row count). Retry a
        # few times, then fail loudly rather than continuing with incomplete data.
        # data is only ever assigned AFTER assert_api_response succeeds (via the
        # separate `parsed` local), so `data is None` below stays a reliable
        # signal even when a response is read successfully but fails validation
        # -- that must not leave a stale, already-rejected payload in `data`.
        data = None
        last_error = None
        for attempt in range(1, SCRAPER_MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': SCRAPER_USER_AGENT})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                    parsed = json.load(response)
                assert_api_response(parsed)
                data = parsed
                break
            except AssertionError:
                # A structural/schema failure won't fix itself on retry (e.g. SBAB
                # changed the API shape) -- that's the real risk this project exists
                # to catch, so fail immediately rather than burning retries on it.
                raise
            except Exception as e:
                last_error = e
                if attempt < SCRAPER_MAX_RETRIES:
                    print(f"  Retry {attempt}/{SCRAPER_MAX_RETRIES - 1} at LTV={ltv:.3f}, VOL={loan_vol}: {e}")
                    time.sleep(SCRAPER_RETRY_DELAY_SECONDS)

        if data is None:
            raise RuntimeError(
                f"Probe at LTV={ltv:.3f}, VOL={loan_vol} failed after {SCRAPER_MAX_RETRIES} attempts: {last_error}"
            )

        for item in data:
            rows.append({
                'url': url,
                'loan_amount': loan_vol,
                'ltv': ltv,
                'period': item['Rantebindningstid'],
                'offered_interest_rate': item['Rantesats'],
                'scraped_at': scrape_time,
                'bank': 'SBAB',
                'json': json.dumps(item)
            })

        if SCRAPER_PAUSE_SECONDS:
            time.sleep(SCRAPER_PAUSE_SECONDS)

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i + 1}/{total}")

    print(f"Scrape complete: {len(rows)} rows from {total} probe points")

    # Convert to DataFrame with correct dtypes
    df = pd.DataFrame(rows)
    df['loan_amount'] = df['loan_amount'].astype('int64')
    df['ltv'] = df['ltv'].astype('float64')
    df['period'] = df['period'].astype('int64')
    df['offered_interest_rate'] = df['offered_interest_rate'].astype('float64')

    assert_scraper_output(df)
    return df
