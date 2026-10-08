"""
Step 3a: Convert Raw Scraper Output to Analysis-Ready DataFrames

Bins raw (LTV, VOL) values and computes per-bin statistics.

INPUTS:
    - scraper_df: from step 1 (SCRAPER_OUTPUT_SCHEMA)
    - boundaries_minimal.yaml (bin edges and labels)
    - data/list_rates.csv (to compute discount = list_rate - offered_rate)

OUTPUTS:
    - todays_pricing_df: pass-through of scraper_df
    - bin_uniform_df: flat_{N}m = True if discount uniform within bin for maturity N
    - bin_mean_df: mean_discount_{N}m = mean discount per bin (full precision)

I/O CONTRACT: see io_contracts.py (BIN_UNIFORM_SCHEMA, BIN_MEAN_SCHEMA)
"""
from pathlib import Path

import pandas as pd
import yaml

from io_contracts import (
    assert_scraper_output,
    assert_todays_pricing_df,
    assert_bin_uniform_df,
    assert_bin_mean_df,
    VALID_MATURITIES,
    LTV_BIN_RIGHT_CLOSED,
    VOL_BIN_RIGHT_CLOSED,
    data_dir,
)


def load_boundaries(config_file='boundaries_minimal.yaml'):
    """Load LTV and VOL bins from YAML config."""
    config_path = data_dir() / config_file
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config['ltv_bins'], config['vol_bins'], config['ltv_labels'], config['vol_labels']


def load_current_list_rates(list_rates_path=None):
    """Load current list rates (where valid_to is empty)."""
    if list_rates_path is None:
        list_rates_path = data_dir() / 'list_rates.csv'
    df = pd.read_csv(list_rates_path)
    current = df[df['valid_to'].isna() | (df['valid_to'] == '')]
    return dict(zip(current['maturity'], current['list_rate']))


def assign_bin(value, bins, labels, *, right):
    """
    Assign a value to a bin, return the label.

    `right` follows pandas.cut's convention and must be passed explicitly, by keyword
    (no default): True means bins are half-open as (low, high]; False means [low, high).
    This matters because SBAB's real pricing is closed on OPPOSITE sides per axis
    (confirmed 2026-09-29 by probing exact bin-edge values against the live API): LTV
    bins are (low, high] (right=True) -- e.g. LTV=0.80 prices with "(79-80)%", not
    "(80-85)%" -- while VOL bins are [low, high) (right=False) -- e.g. VOL=1,500,000
    prices with "(1.5-2)M", not "(1-1.5)M". With right=True, the very first bin is also
    closed on the left (matches pandas.cut's include_lowest=True), so a value exactly
    equal to the global lower edge (e.g. LTV=0.0) still lands in the first bin rather
    than falling through to the last one -- there's no bin below it to claim it instead.
    In today's pipeline none of this changes real output, since every probe is
    generated at boundary +/- epsilon and never lands exactly on an edge for the
    config both call sites actually use (see LTV_EPSILON/VOL_EPSILON in
    io_contracts.py) -- but get this backwards and a future caller binning a raw,
    non-probe value (e.g. a customer-facing rate lookup) will silently pick the wrong
    LTV bin. A value outside [bins[0], bins[-1]] (or NaN) also silently falls through
    to the last bin's label -- this function does no range validation; see the
    commented-out assert_ltv_range TODO in io_contracts.py for the proper place to add it.
    """
    for i in range(len(bins) - 1):
        if right:
            in_bin = (bins[i] < value <= bins[i + 1]) or (i == 0 and value == bins[0])
        else:
            in_bin = bins[i] <= value < bins[i + 1]
        if in_bin:
            return labels[i]
    return labels[-1]


def convert_scraper_to_analysis_dfs(scraper_df, config_file='boundaries_minimal.yaml', list_rates_path=None):
    """
    Convert raw scraper output to analysis-ready DataFrames.

    Args:
        scraper_df: DataFrame from step 1 (scraper output)
        config_file: YAML config file with bin definitions (default: boundaries_minimal.yaml)
        list_rates_path: Path to list_rates.csv (default: data/list_rates.csv)

    Returns:
        todays_pricing_df: pass-through of scraper_df
        bin_uniform_df: per-bin uniformity flags
        bin_mean_df: per-bin mean discounts
    """
    assert_scraper_output(scraper_df)

    ltv_bins, vol_bins, ltv_labels, vol_labels = load_boundaries(config_file)
    list_rates = load_current_list_rates(list_rates_path)

    # Assign bins and compute discounts
    df = scraper_df.copy()
    df['ltv_bin'] = df['ltv'].apply(lambda x: assign_bin(x, ltv_bins, ltv_labels, right=LTV_BIN_RIGHT_CLOSED))
    df['vol_bin'] = df['loan_amount'].apply(lambda x: assign_bin(x, vol_bins, vol_labels, right=VOL_BIN_RIGHT_CLOSED))
    df['discount'] = df.apply(lambda row: list_rates[row['period']] - row['offered_interest_rate'], axis=1)

    # Build uniform and mean DataFrames
    uniform_rows = []
    mean_rows = []

    for (ltv_bin, vol_bin), grp in df.groupby(['ltv_bin', 'vol_bin']):
        uniform_row = {'ltv_bin': ltv_bin, 'vol_bin': vol_bin}
        mean_row = {'ltv_bin': ltv_bin, 'vol_bin': vol_bin}

        for m in VALID_MATURITIES:
            m_grp = grp[grp['period'] == m]['discount']
            uniform_row[f'flat_{m}m'] = (m_grp.nunique() == 1) if len(m_grp) > 0 else True
            mean_row[f'mean_discount_{m}m'] = m_grp.mean() if len(m_grp) > 0 else float('nan')

        uniform_rows.append(uniform_row)
        mean_rows.append(mean_row)

    # Build output DataFrames with correct dtypes
    bin_uniform_df = pd.DataFrame(uniform_rows)
    for m in VALID_MATURITIES:
        bin_uniform_df[f'flat_{m}m'] = bin_uniform_df[f'flat_{m}m'].astype('bool')

    bin_mean_df = pd.DataFrame(mean_rows)
    for m in VALID_MATURITIES:
        bin_mean_df[f'mean_discount_{m}m'] = bin_mean_df[f'mean_discount_{m}m'].astype('float64')

    # todays_pricing_df is pass-through
    todays_pricing_df = scraper_df.copy()

    # Validate outputs
    assert_todays_pricing_df(todays_pricing_df)
    assert_bin_uniform_df(bin_uniform_df)
    assert_bin_mean_df(bin_mean_df)

    return todays_pricing_df, bin_uniform_df, bin_mean_df
